"""Resource-aware Celery pool autoscaling for face inference workers.

The controller runs in the Celery parent process.  It never loads InsightFace;
each prefork child owns its own lazy model instance.  Capacity is bounded by
CPU, host memory, and (when NVML is available) physical GPU memory.  Runtime
changes happen one child at a time so a burst cannot initialise several CUDA
contexts simultaneously.
"""
from __future__ import annotations

import math
import os
import socket
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from celery.utils.log import get_logger
from celery.worker import state
from celery.worker.autoscale import Autoscaler

from ..config import get_settings


logger = get_logger(__name__)
MIB = 1024 * 1024
CONTROLLER_HEARTBEAT_PREFIX = "pg:telemetry:heartbeat:controller"
CONTROLLER_HEARTBEAT_TTL_SECONDS = 10


@dataclass(frozen=True)
class ResourceSample:
    cpu_percent: Optional[float] = None
    cpu_capacity: float = 1.0
    memory_available_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None
    gpu_available: bool = False
    gpu_index: Optional[int] = None
    gpu_uuid: Optional[str] = None
    gpu_percent: Optional[float] = None
    gpu_memory_used_bytes: Optional[int] = None
    gpu_memory_total_bytes: Optional[int] = None

    @property
    def gpu_memory_free_bytes(self) -> Optional[int]:
        if self.gpu_memory_used_bytes is None or self.gpu_memory_total_bytes is None:
            return None
        return max(0, self.gpu_memory_total_bytes - self.gpu_memory_used_bytes)


@dataclass(frozen=True)
class WorkerLimits:
    pool: str
    autoscale_enabled: bool
    min_concurrency: int
    max_concurrency: int
    reason: str


def _read_number(path: str) -> Optional[int]:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
        if not value or value == "max":
            return None
        return int(value)
    except (OSError, TypeError, ValueError):
        return None


def _cgroup_memory(
    total_bytes: Optional[int], available_bytes: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    """Clamp psutil host figures to the current Linux cgroup, when present."""
    limit = _read_number("/sys/fs/cgroup/memory.max")
    current = _read_number("/sys/fs/cgroup/memory.current")
    if limit is None:
        limit = _read_number("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        current = _read_number("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    # cgroup v1 often exposes a sentinel near LONG_MAX when unlimited.
    if limit is None or limit >= (1 << 60):
        return total_bytes, available_bytes
    bounded_total = min(total_bytes, limit) if total_bytes is not None else limit
    cgroup_available = max(0, limit - (current or 0))
    bounded_available = (
        min(available_bytes, cgroup_available)
        if available_bytes is not None
        else cgroup_available
    )
    return bounded_total, bounded_available


def _effective_cpu_capacity(psutil_module: Any) -> float:
    capacities = [float(max(1, psutil_module.cpu_count(logical=True) or 1))]
    try:
        affinity = psutil_module.Process(os.getpid()).cpu_affinity()
        if affinity:
            capacities.append(float(len(affinity)))
    except (AttributeError, OSError, psutil_module.Error):
        pass
    try:
        quota_text = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").strip()
        quota, period = quota_text.split()[:2]
        if quota != "max" and float(period) > 0:
            capacities.append(max(0.01, float(quota) / float(period)))
    except (OSError, TypeError, ValueError):
        pass
    return max(0.01, min(capacities))


class ResourceProbe:
    """Best-effort host and selected-GPU sampler with no CUDA initialisation."""

    def __init__(self, settings_override: Any = None):
        self.settings = settings_override or get_settings()
        self._psutil = None
        self._nvml = None
        self._nvml_handle = None
        self._nvml_initialization_attempted = False
        self._gpu_index: Optional[int] = None
        self._gpu_uuid: Optional[str] = None
        try:
            import psutil

            self._psutil = psutil
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    def _gpu_handle(self):
        if self._nvml_handle is not None:
            return self._nvml_handle
        if self._nvml_initialization_attempted:
            return None
        self._nvml_initialization_attempted = True
        visible = os.environ.get("CUDA_VISIBLE_DEVICES")
        if visible is not None and visible.strip() in ("", "-1"):
            return None
        try:
            import pynvml

            pynvml.nvmlInit()
            selector = (visible or "").split(",", 1)[0].strip()
            if selector.upper().startswith(("GPU-", "MIG-")):
                handle = pynvml.nvmlDeviceGetHandleByUUID(selector)
                index = None
            else:
                index = (
                    int(selector)
                    if selector.isdigit()
                    else int(self.settings.WORKER_AUTOSCALE_GPU_DEVICE_INDEX)
                )
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            raw_uuid = pynvml.nvmlDeviceGetUUID(handle)
            if isinstance(raw_uuid, bytes):
                raw_uuid = raw_uuid.decode("utf-8", "replace")
            self._nvml = pynvml
            self._nvml_handle = handle
            self._gpu_index = index
            self._gpu_uuid = str(raw_uuid)
            return handle
        except Exception:
            return None

    def sample(self) -> ResourceSample:
        cpu_percent = None
        cpu_capacity = 1.0
        memory_total = None
        memory_available = None
        if self._psutil is not None:
            try:
                cpu_percent = float(self._psutil.cpu_percent(interval=None))
                cpu_capacity = _effective_cpu_capacity(self._psutil)
                memory = self._psutil.virtual_memory()
                memory_total = int(memory.total)
                memory_available = int(memory.available)
                if os.name != "nt":
                    memory_total, memory_available = _cgroup_memory(
                        memory_total, memory_available
                    )
            except Exception:
                pass

        handle = self._gpu_handle()
        if handle is None or self._nvml is None:
            return ResourceSample(
                cpu_percent=cpu_percent,
                cpu_capacity=cpu_capacity,
                memory_available_bytes=memory_available,
                memory_total_bytes=memory_total,
            )
        try:
            utilization = self._nvml.nvmlDeviceGetUtilizationRates(handle)
            memory = self._nvml.nvmlDeviceGetMemoryInfo(handle)
            return ResourceSample(
                cpu_percent=cpu_percent,
                cpu_capacity=cpu_capacity,
                memory_available_bytes=memory_available,
                memory_total_bytes=memory_total,
                gpu_available=True,
                gpu_index=self._gpu_index,
                gpu_uuid=self._gpu_uuid,
                gpu_percent=float(utilization.gpu),
                gpu_memory_used_bytes=int(memory.used),
                gpu_memory_total_bytes=int(memory.total),
            )
        except Exception:
            return ResourceSample(
                cpu_percent=cpu_percent,
                cpu_capacity=cpu_capacity,
                memory_available_bytes=memory_available,
                memory_total_bytes=memory_total,
            )


def _memory_capacity(total_bytes: Optional[int], reserve_mb: int, per_process_mb: int) -> int:
    if total_bytes is None:
        return 2**31 - 1
    usable_mb = max(0, total_bytes // MIB - int(reserve_mb))
    return max(1, usable_mb // max(1, int(per_process_mb)))


def resolve_worker_limits(
    settings_override: Any = None,
    sample: Optional[ResourceSample] = None,
    *,
    platform_name: Optional[str] = None,
) -> WorkerLimits:
    """Resolve a safe startup ceiling before Celery creates its process pool."""
    settings = settings_override or get_settings()
    platform_value = (platform_name or os.name).lower()
    if platform_value in ("nt", "windows", "win32"):
        return WorkerLimits("solo", False, 1, 1, "windows_solo")

    sample = sample or ResourceProbe(settings).sample()
    configured_min = max(1, int(settings.WORKER_AUTOSCALE_MIN_CONCURRENCY))
    hard_max = max(configured_min, int(settings.WORKER_AUTOSCALE_MAX_CONCURRENCY))
    cpu_max = max(1, int(math.floor(sample.cpu_capacity)))
    ram_max = _memory_capacity(
        sample.memory_total_bytes,
        settings.WORKER_AUTOSCALE_SYSTEM_MEMORY_RESERVE_MB,
        settings.WORKER_AUTOSCALE_SYSTEM_MEMORY_PER_PROCESS_MB,
    )
    capacities = [hard_max, cpu_max, ram_max]
    if sample.gpu_available:
        capacities.append(_memory_capacity(
            sample.gpu_memory_total_bytes,
            settings.WORKER_AUTOSCALE_GPU_MEMORY_RESERVE_MB,
            settings.WORKER_AUTOSCALE_GPU_MEMORY_PER_PROCESS_MB,
        ))
    else:
        capacities.append(max(1, int(settings.WORKER_AUTOSCALE_CPU_MAX_CONCURRENCY)))
    resolved_max = max(1, min(capacities))
    resolved_min = min(configured_min, resolved_max)
    enabled = bool(settings.WORKER_AUTOSCALE_ENABLED and resolved_max > resolved_min)
    if not settings.WORKER_AUTOSCALE_ENABLED:
        resolved_max = resolved_min
        reason = "autoscale_disabled"
    elif resolved_max <= resolved_min:
        reason = "resolved_capacity_one"
    else:
        reason = "adaptive_ready"
    return WorkerLimits("prefork", enabled, resolved_min, resolved_max, reason)


_snapshot_lock = threading.Lock()
_controller_snapshot: dict[str, Any] = {
    "autoscale_enabled": False,
    "processing_concurrency": 1,
    "processing_concurrency_min": 1,
    "processing_concurrency_max": 1,
    "processing_control_reason": "not_started",
}
_heartbeat_client = None
_heartbeat_client_lock = threading.Lock()


def get_controller_snapshot() -> dict[str, Any]:
    """Return the latest typed snapshot in the current controller process."""
    with _snapshot_lock:
        return dict(_controller_snapshot)


def _redis_client():
    global _heartbeat_client
    if _heartbeat_client is not None:
        return _heartbeat_client
    with _heartbeat_client_lock:
        if _heartbeat_client is not None:
            return _heartbeat_client
        try:
            from redis import Redis

            settings = get_settings()
            _heartbeat_client = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
        except Exception:
            return None
    return _heartbeat_client


def publish_controller_snapshot(snapshot: dict[str, Any]) -> None:
    """Publish an expiring heartbeat without affecting processing correctness."""
    typed = dict(snapshot)
    typed.setdefault("timestamp", time.time())
    typed.setdefault("component", "controller")
    typed.setdefault("host_id", socket.gethostname())
    typed.setdefault("pid", os.getpid())
    with _snapshot_lock:
        _controller_snapshot.clear()
        _controller_snapshot.update(typed)

    mapping = {
        key: int(value) if isinstance(value, bool) else value
        for key, value in typed.items()
        if value is not None
    }
    client = _redis_client()
    if client is None:
        return
    key = f"{CONTROLLER_HEARTBEAT_PREFIX}:{typed['host_id']}:{typed['pid']}"
    try:
        pipe = client.pipeline(transaction=False)
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, CONTROLLER_HEARTBEAT_TTL_SECONDS)
        pipe.execute()
    except Exception:
        return


class ResourceAwareAutoscaler(Autoscaler):
    """Grow/shrink the prefork pool one child at a time with hysteresis."""

    def __init__(
        self,
        pool,
        max_concurrency,
        min_concurrency=0,
        worker=None,
        keepalive=None,
        mutex=None,
        *,
        settings_override: Any = None,
        resource_probe: Optional[ResourceProbe] = None,
        queue_depth: Optional[Callable[[], int]] = None,
        clock: Optional[Callable[[], float]] = None,
        publisher: Optional[Callable[[dict[str, Any]], None]] = None,
        platform_name: Optional[str] = None,
    ):
        self.settings = settings_override or get_settings()
        self.resource_probe = resource_probe or ResourceProbe(self.settings)
        initial_sample = self.resource_probe.sample()
        platform_value = (platform_name or os.name).lower()
        limits = resolve_worker_limits(
            self.settings,
            initial_sample,
            platform_name=platform_value,
        )
        effective_max = max(1, min(int(max_concurrency), limits.max_concurrency))
        effective_min = max(1, min(int(min_concurrency or 1), effective_max))
        interval = max(
            0.5,
            float(keepalive or self.settings.WORKER_AUTOSCALE_SAMPLE_INTERVAL_SECONDS),
        )
        super().__init__(
            pool,
            effective_max,
            effective_min,
            worker=worker,
            keepalive=interval,
            mutex=mutex,
        )
        self.autoscale_enabled = bool(
            self.settings.WORKER_AUTOSCALE_ENABLED
            and platform_value not in ("nt", "windows", "win32")
            and effective_max > effective_min
        )
        self._queue_depth = queue_depth or (lambda: len(state.reserved_requests))
        self._clock = clock or time.monotonic
        self._publisher = publisher or publish_controller_snapshot
        self._last_resize_at = self._clock()
        self._idle_since: Optional[float] = None
        self._healthy_growth_samples = 0
        self._reason = limits.reason
        self._sample = initial_sample
        self._gpu_required = initial_sample.gpu_available

    @property
    def qty(self):
        try:
            return max(0, int(self._queue_depth()))
        except Exception:
            return 0

    def _gpu_free_mb(self, sample: ResourceSample) -> Optional[float]:
        free = sample.gpu_memory_free_bytes
        return None if free is None else free / MIB

    def _pressure_reason(self, sample: ResourceSample) -> Optional[str]:
        if self._gpu_required and not sample.gpu_available:
            return "gpu_metrics_unavailable"
        if (
            sample.memory_available_bytes is not None
            and sample.memory_available_bytes / MIB
            < float(self.settings.WORKER_AUTOSCALE_SYSTEM_MEMORY_RESERVE_MB)
        ):
            return "system_memory_pressure"
        gpu_free_mb = self._gpu_free_mb(sample)
        if (
            sample.gpu_available
            and gpu_free_mb is not None
            and gpu_free_mb < float(self.settings.WORKER_AUTOSCALE_GPU_MEMORY_RESERVE_MB)
        ):
            return "gpu_memory_pressure"
        if (
            sample.cpu_percent is not None
            and sample.cpu_percent >= float(self.settings.WORKER_AUTOSCALE_CPU_SHRINK_PERCENT)
        ):
            return "cpu_pressure"
        return None

    def _has_growth_headroom(self, sample: ResourceSample) -> tuple[bool, str]:
        if (
            sample.cpu_percent is not None
            and sample.cpu_percent > float(self.settings.WORKER_AUTOSCALE_CPU_GROW_PERCENT)
        ):
            return False, "cpu_busy"
        if sample.memory_available_bytes is not None:
            required_mb = (
                float(self.settings.WORKER_AUTOSCALE_SYSTEM_MEMORY_RESERVE_MB)
                + float(self.settings.WORKER_AUTOSCALE_SYSTEM_MEMORY_PER_PROCESS_MB)
            )
            if sample.memory_available_bytes / MIB < required_mb:
                return False, "system_memory_headroom"
        if sample.gpu_available:
            if (
                sample.gpu_percent is not None
                and sample.gpu_percent > float(self.settings.WORKER_AUTOSCALE_GPU_GROW_PERCENT)
            ):
                return False, "gpu_busy"
            gpu_free_mb = self._gpu_free_mb(sample)
            required_mb = (
                float(self.settings.WORKER_AUTOSCALE_GPU_MEMORY_RESERVE_MB)
                + float(self.settings.WORKER_AUTOSCALE_GPU_MEMORY_PER_PROCESS_MB)
            )
            if gpu_free_mb is not None and gpu_free_mb < required_mb:
                return False, "gpu_memory_headroom"
        return True, "headroom_available"

    def _grow_one(self, now: float) -> bool:
        try:
            self.pool.grow(1)
            self._last_scale_up = now
            self._last_resize_at = now
            logger.info(
                "Resource autoscaler growing face pool to %s/%s",
                self.processes,
                self.max_concurrency,
            )
            return True
        except Exception as exc:
            logger.warning("Resource autoscaler could not grow the pool: %s", exc)
            self._reason = "pool_grow_failed"
            return False

    def _shrink_one(self, now: float) -> bool:
        before = self.processes
        try:
            # Billiard selects an inactive child and terminate_controlled() is
            # called by Pool.shrink; process exit releases that child's CUDA
            # context and GPU allocations.
            self.pool.shrink(1)
            self._last_resize_at = now
            logger.info(
                "Resource autoscaler shrinking face pool to %s/%s",
                self.processes,
                self.max_concurrency,
            )
            return self.processes < before
        except ValueError:
            self._reason = "pool_busy_cannot_shrink"
            return False
        except Exception as exc:
            logger.warning("Resource autoscaler could not shrink the pool: %s", exc)
            self._reason = "pool_shrink_failed"
            return False

    def _publish(self) -> None:
        sample = self._sample
        snapshot = {
            "autoscale_enabled": self.autoscale_enabled,
            "processing_concurrency": int(self.processes),
            "processing_concurrency_min": int(self.min_concurrency),
            "processing_concurrency_max": int(self.max_concurrency),
            "processing_control_reason": self._reason,
            "processing_queue_depth": int(self.qty),
            "processing_pool": "prefork",
            "autoscale_sample_cpu_percent": sample.cpu_percent,
            "autoscale_sample_gpu_percent": sample.gpu_percent,
            "autoscale_sample_gpu_memory_used_bytes": sample.gpu_memory_used_bytes,
            "autoscale_sample_gpu_memory_total_bytes": sample.gpu_memory_total_bytes,
            "autoscale_gpu_available": sample.gpu_available,
            "autoscale_gpu_index": sample.gpu_index,
            "autoscale_gpu_uuid": sample.gpu_uuid,
            "timestamp": time.time(),
        }
        self._publisher(snapshot)

    def _maybe_scale(self, req=None):
        del req
        now = self._clock()
        self._sample = self.resource_probe.sample()
        current = self.processes
        queued = self.qty
        changed = False

        pressure = self._pressure_reason(self._sample)
        if pressure is not None:
            self._healthy_growth_samples = 0
            self._idle_since = None
            self._reason = pressure
            if current > self.min_concurrency:
                changed = self._shrink_one(now)
        elif queued < current:
            self._healthy_growth_samples = 0
            self._idle_since = self._idle_since or now
            self._reason = "idle_cooldown"
            idle_for = now - self._idle_since
            resize_age = now - self._last_resize_at
            if (
                current > self.min_concurrency
                and idle_for >= float(self.settings.WORKER_AUTOSCALE_IDLE_SECONDS)
                and resize_age >= float(self.settings.WORKER_AUTOSCALE_SCALE_DOWN_COOLDOWN_SECONDS)
            ):
                self._reason = "idle_scale_down"
                changed = self._shrink_one(now)
        else:
            self._idle_since = None
            if not self.autoscale_enabled:
                self._healthy_growth_samples = 0
                self._reason = "autoscale_disabled" if current == self.max_concurrency else "fixed_capacity"
            elif current >= self.max_concurrency:
                self._healthy_growth_samples = 0
                self._reason = "at_max_concurrency"
            elif queued <= current:
                self._healthy_growth_samples = 0
                self._reason = "no_queue_pressure"
            elif now - self._last_resize_at < float(
                self.settings.WORKER_AUTOSCALE_SCALE_UP_COOLDOWN_SECONDS
            ):
                self._healthy_growth_samples = 0
                self._reason = "scale_up_cooldown"
            else:
                has_headroom, reason = self._has_growth_headroom(self._sample)
                if not has_headroom:
                    self._healthy_growth_samples = 0
                    self._reason = reason
                else:
                    self._healthy_growth_samples += 1
                    required = max(1, int(self.settings.WORKER_AUTOSCALE_GROW_SAMPLES))
                    self._reason = "waiting_for_sustained_headroom"
                    if self._healthy_growth_samples >= required:
                        self._healthy_growth_samples = 0
                        self._reason = "queue_pressure_scale_up"
                        changed = self._grow_one(now)

        self._publish()
        return changed

    def info(self):
        info = super().info()
        info.update({
            "enabled": self.autoscale_enabled,
            "reason": self._reason,
            "resources": asdict(self._sample),
        })
        return info
