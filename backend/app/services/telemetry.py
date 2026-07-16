"""Transient cross-process throughput and resource telemetry.

PostgreSQL owns exact batch progress. Redis carries only short rolling rate
buckets and expiring process heartbeats, so outages degrade meters without
corrupting batch counts.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from typing import Any, Optional

from ..config import get_settings

settings = get_settings()

RATE_WINDOW_SECONDS = 30
RATE_TTL_SECONDS = 120
HEARTBEAT_TTL_SECONDS = 10
HEARTBEAT_INTERVAL_SECONDS = 1.0
KEY_PREFIX = "pg:telemetry"
RATE_KEY_PREFIX = f"{KEY_PREFIX}:rate:v2"
RATE_BUCKET_COUNT = RATE_TTL_SECONDS

# One hash field is reused per second modulo RATE_BUCKET_COUNT. The epoch is
# stored in the value so an old slot can never contaminate the current window.
# Lua keeps concurrent worker completions in the same second atomic.
_RATE_BUCKET_LUA = """
local current = redis.call('HGET', KEYS[1], ARGV[1])
local epoch = tonumber(ARGV[2])
local images = tonumber(ARGV[3])
local faces = tonumber(ARGV[4])
if current then
  local old_epoch, old_images, old_faces = string.match(
    current, '^(%-?%d+):(%-?%d+):(%-?%d+)$'
  )
  if tonumber(old_epoch) == epoch then
    images = images + tonumber(old_images)
    faces = faces + tonumber(old_faces)
  end
end
redis.call('HSET', KEYS[1], ARGV[1], epoch .. ':' .. images .. ':' .. faces)
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""

_sync_redis = None
_async_redis = None
_redis_lock = threading.Lock()
_sampler = None
_sampler_lock = threading.Lock()
_local_processor = "unknown"


def _effective_cpu_capacity(psutil_module: Any, process: Any) -> float:
    """Best-effort logical CPU capacity respecting affinity/cgroup quotas."""
    capacities = [float(max(1, psutil_module.cpu_count(logical=True) or 1))]
    try:
        affinity = process.cpu_affinity()
        if affinity:
            capacities.append(float(len(affinity)))
    except (AttributeError, OSError, psutil_module.Error):
        pass
    try:
        with open("/sys/fs/cgroup/cpu.max", "r", encoding="utf-8") as handle:
            quota, period = handle.read().strip().split()[:2]
        if quota != "max" and float(period) > 0:
            capacities.append(max(0.01, float(quota) / float(period)))
    except (OSError, ValueError, IndexError):
        try:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r", encoding="utf-8") as quota_file:
                quota = float(quota_file.read().strip())
            with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r", encoding="utf-8") as period_file:
                period = float(period_file.read().strip())
            if quota > 0 and period > 0:
                capacities.append(max(0.01, quota / period))
        except (OSError, ValueError):
            pass
    return max(0.01, min(capacities))


def _sync_client():
    global _sync_redis
    if _sync_redis is not None:
        return _sync_redis
    with _redis_lock:
        if _sync_redis is None:
            try:
                from redis import Redis

                _sync_redis = Redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    health_check_interval=30,
                )
            except Exception:
                return None
    return _sync_redis


def _async_client():
    global _async_redis
    if _async_redis is not None:
        return _async_redis
    try:
        from redis.asyncio import Redis

        _async_redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    except Exception:
        return None
    return _async_redis


def _rate_keys(batch_id: uuid.UUID, tenant_id: uuid.UUID) -> tuple[str, str, str]:
    return (
        f"{RATE_KEY_PREFIX}:batch:{batch_id}",
        f"{RATE_KEY_PREFIX}:tenant:{tenant_id}",
        f"{RATE_KEY_PREFIX}:global",
    )


def record_completion_sync(
    *,
    batch_id: uuid.UUID,
    tenant_id: uuid.UUID,
    faces_detected: int,
    images: int = 1,
) -> None:
    """Record one already-committed, idempotent terminal transition."""
    client = _sync_client()
    if client is None:
        return
    second = int(time.time())
    try:
        pipe = client.pipeline(transaction=False)
        for key in _rate_keys(batch_id, tenant_id):
            pipe.eval(
                _RATE_BUCKET_LUA,
                1,
                key,
                f"b:{second % RATE_BUCKET_COUNT}",
                second,
                max(0, int(images)),
                max(0, int(faces_detected or 0)),
                RATE_TTL_SECONDS,
            )
        pipe.execute()
    except Exception:
        # Metrics must never fail a completed photo task.
        return


def _rates_from_hash(
    values: dict[str, Any],
    *,
    now_second: Optional[int] = None,
    window_seconds: int = RATE_WINDOW_SECONDS,
) -> tuple[float, float]:
    now_second = int(time.time()) if now_second is None else int(now_second)
    minimum = now_second - max(1, window_seconds) + 1
    image_total = 0
    face_total = 0
    seen_seconds: list[int] = []
    for raw_field, raw_value in (values or {}).items():
        field = str(raw_field)
        if field.startswith("b:"):
            try:
                raw_second, raw_images, raw_faces = str(raw_value).split(":", 2)
                second = int(raw_second)
                images = int(raw_images)
                faces = int(raw_faces)
            except (TypeError, ValueError):
                continue
            if second < minimum or second > now_second:
                continue
            seen_seconds.append(second)
            image_total += images
            face_total += faces
            continue
        try:
            # Retain parsing for old fields during tests and rolling deploys.
            # New writes live in the bounded v2 namespace above.
            kind, raw_second = field.split(":", 1)
            second = int(raw_second)
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if second < minimum or second > now_second:
            continue
        seen_seconds.append(second)
        if kind == "i":
            image_total += value
        elif kind == "f":
            face_total += value

    if not seen_seconds:
        return 0.0, 0.0
    elapsed = max(1, min(window_seconds, now_second - min(seen_seconds) + 1))
    return round(image_total / elapsed, 3), round(face_total / elapsed, 3)


async def read_rate(
    *,
    batch_id: Optional[uuid.UUID] = None,
    tenant_id: Optional[uuid.UUID] = None,
) -> tuple[float, float]:
    client = _async_client()
    if client is None:
        return 0.0, 0.0
    if batch_id is not None:
        key = f"{RATE_KEY_PREFIX}:batch:{batch_id}"
    elif tenant_id is not None:
        key = f"{RATE_KEY_PREFIX}:tenant:{tenant_id}"
    else:
        key = f"{RATE_KEY_PREFIX}:global"
    try:
        return _rates_from_hash(await client.hgetall(key))
    except Exception:
        return 0.0, 0.0


def set_local_processor(processor: Optional[str]) -> None:
    global _local_processor
    value = (processor or "").lower()
    _local_processor = value if value in ("cpu", "gpu") else "unknown"


def detect_runtime_processor() -> str:
    """Inspect the already-loaded InsightFace sessions without loading a model."""
    try:
        from . import ml_pipeline

        app = getattr(ml_pipeline, "_app", None)
        if app is None:
            return _local_processor
        saw_cpu = False
        for model in getattr(app, "models", {}).values():
            session = getattr(model, "session", None)
            if session is None:
                continue
            providers = session.get_providers()
            if providers and providers[0] == "CUDAExecutionProvider":
                set_local_processor("gpu")
                return "gpu"
            if "CPUExecutionProvider" in providers:
                saw_cpu = True
        if saw_cpu:
            set_local_processor("cpu")
            return "cpu"
    except Exception:
        pass
    return _local_processor


class _ProcessSampler:
    def __init__(self, component: str):
        self.component = component
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name=f"telemetry-{component}",
            daemon=True,
        )
        self.hostname = socket.gethostname()
        self.key = f"{KEY_PREFIX}:heartbeat:{component}:{self.hostname}:{os.getpid()}"
        from .deployment_identity import database_fingerprint

        self.database_fingerprint = database_fingerprint()
        self._processes: dict[int, Any] = {}
        self._nvml_ready = False
        self.cpu_capacity = 1.0

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)
        client = _sync_client()
        if client is not None:
            try:
                client.delete(self.key)
            except Exception:
                pass

    def _cpu_percent(self) -> Optional[float]:
        try:
            import psutil

            root = psutil.Process(os.getpid())
            self.cpu_capacity = _effective_cpu_capacity(psutil, root)
            processes = [root, *root.children(recursive=True)]
            live_pids = {p.pid for p in processes}
            for stale_pid in set(self._processes) - live_pids:
                self._processes.pop(stale_pid, None)
            total = 0.0
            for process in processes:
                cached = self._processes.setdefault(process.pid, process)
                try:
                    total += float(cached.cpu_percent(interval=None))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return round(min(100.0, total / self.cpu_capacity), 1)
        except Exception:
            return None

    def _gpu_metrics(self) -> dict[str, int | float]:
        # NVML is device-wide. Sample only worker components to avoid counting
        # the same device again from the colocated web process.
        if self.component != "worker":
            return {}
        try:
            import pynvml

            if not self._nvml_ready:
                pynvml.nvmlInit()
                self._nvml_ready = True
            count = pynvml.nvmlDeviceGetCount()
            if count <= 0:
                return {}
            utilizations = []
            used = 0
            total = 0
            for index in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                utilizations.append(float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu))
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                used += int(memory.used)
                total += int(memory.total)
            return {
                "gpu_percent": round(sum(utilizations) / len(utilizations), 1),
                "gpu_memory_used_bytes": used,
                "gpu_memory_total_bytes": total,
            }
        except Exception:
            return {}

    def _publish(self) -> None:
        client = _sync_client()
        if client is None:
            return
        cpu = self._cpu_percent()
        processor = detect_runtime_processor() if self.component == "worker" else "unknown"
        mapping: dict[str, Any] = {
            "component": self.component,
            "host_id": self.hostname,
            "pid": os.getpid(),
            "processor": processor,
            "database_fingerprint": self.database_fingerprint,
            "timestamp": time.time(),
            "cpu_capacity": self.cpu_capacity,
        }
        if cpu is not None:
            mapping["cpu_percent"] = cpu
        mapping.update(self._gpu_metrics())
        try:
            pipe = client.pipeline(transaction=False)
            pipe.hset(self.key, mapping=mapping)
            pipe.expire(self.key, HEARTBEAT_TTL_SECONDS)
            pipe.execute()
        except Exception:
            return

    def _run(self) -> None:
        # Prime psutil's non-blocking counters before publishing the first
        # meaningful sample.
        self._cpu_percent()
        while not self.stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            self._publish()


def start_resource_sampler(component: str) -> None:
    global _sampler
    with _sampler_lock:
        if _sampler is not None:
            return
        try:
            _sampler = _ProcessSampler(component)
            _sampler.start()
        except Exception:
            _sampler = None


def stop_resource_sampler() -> None:
    global _sampler
    with _sampler_lock:
        sampler, _sampler = _sampler, None
    if sampler is not None:
        sampler.stop()


def _aggregate_resource_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    now = time.time()
    fresh = []
    for row in rows:
        try:
            if now - float(row.get("timestamp", 0)) <= HEARTBEAT_TTL_SECONDS:
                fresh.append(row)
        except (TypeError, ValueError):
            continue

    workers = [row for row in fresh if row.get("component") == "worker"]
    web_fingerprints = {
        str(row.get("database_fingerprint"))
        for row in fresh
        if row.get("component") == "web" and row.get("database_fingerprint")
    }
    worker_fingerprints = {
        str(row.get("database_fingerprint"))
        for row in workers
        if row.get("database_fingerprint")
    }
    database_mismatch = bool(
        web_fingerprints
        and worker_fingerprints
        and (len(web_fingerprints | worker_fingerprints) > 1)
    )
    web_database_fingerprint = (
        sorted(web_fingerprints)[0] if web_fingerprints else None
    )
    processors = {
        row.get("processor") for row in workers if row.get("processor") in ("cpu", "gpu")
    }
    if not processors:
        processor = "unknown"
    elif len(processors) == 1:
        processor = next(iter(processors))
    else:
        processor = "mixed"

    cpu_by_host: dict[str, list[dict[str, Any]]] = {}
    for row in fresh:
        if "cpu_percent" in row:
            cpu_by_host.setdefault(str(row.get("host_id", "unknown")), []).append(row)
    weighted_cpu = 0.0
    total_capacity = 0.0
    for host_rows in cpu_by_host.values():
        try:
            capacity = max(
                0.01,
                max(float(row.get("cpu_capacity", 1.0)) for row in host_rows),
            )
            host_percent = min(
                100.0,
                sum(float(row.get("cpu_percent", 0.0)) for row in host_rows),
            )
        except (TypeError, ValueError):
            continue
        weighted_cpu += host_percent * capacity
        total_capacity += capacity
    cpu_percent = (
        round(weighted_cpu / total_capacity, 1) if total_capacity > 0 else None
    )

    # Deduplicate GPU device snapshots per host if multiple worker processes
    # happen to run on the same machine.
    gpu_by_host: dict[str, dict[str, Any]] = {}
    for row in workers:
        if "gpu_percent" in row:
            gpu_by_host.setdefault(str(row.get("host_id", "unknown")), row)
    gpu_rows = list(gpu_by_host.values())
    gpu_percent = None
    gpu_used = None
    gpu_total = None
    if gpu_rows:
        gpu_percent = round(
            sum(float(row.get("gpu_percent", 0)) for row in gpu_rows) / len(gpu_rows), 1
        )
        gpu_used = sum(int(float(row.get("gpu_memory_used_bytes", 0))) for row in gpu_rows)
        gpu_total = sum(int(float(row.get("gpu_memory_total_bytes", 0))) for row in gpu_rows)

    return {
        "processor": processor,
        "cpu_percent": cpu_percent,
        "gpu_percent": gpu_percent,
        "gpu_memory_used_bytes": gpu_used,
        "gpu_memory_total_bytes": gpu_total,
        "worker_count": len(workers),
        "stale": len(workers) == 0,
        "database_mismatch": database_mismatch,
        "database_fingerprint": web_database_fingerprint,
    }


async def read_resources() -> dict[str, Any]:
    client = _async_client()
    if client is None:
        return _aggregate_resource_rows([])
    try:
        keys = []
        async for key in client.scan_iter(match=f"{KEY_PREFIX}:heartbeat:*", count=100):
            keys.append(key)
        if not keys:
            return _aggregate_resource_rows([])
        pipe = client.pipeline(transaction=False)
        for key in keys:
            pipe.hgetall(key)
        rows = await pipe.execute()
        return _aggregate_resource_rows([row for row in rows if row])
    except Exception:
        return _aggregate_resource_rows([])


async def close_async_client() -> None:
    global _async_redis
    client, _async_redis = _async_redis, None
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass
