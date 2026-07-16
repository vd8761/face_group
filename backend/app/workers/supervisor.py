"""Cross-platform supervisor for the face and Drive Celery nodes."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from ..config import get_settings
from .resource_autoscaler import (
    ResourceProbe,
    ResourceSample,
    WorkerLimits,
    publish_controller_snapshot,
    resolve_worker_limits,
)


@dataclass(frozen=True)
class WorkerLaunchPlan:
    limits: WorkerLimits
    face_command: tuple[str, ...]
    drive_command: tuple[str, ...]


def build_launch_plan(
    settings_override: Any = None,
    sample: Optional[ResourceSample] = None,
    *,
    platform_name: Optional[str] = None,
    executable: Optional[str] = None,
) -> WorkerLaunchPlan:
    settings = settings_override or get_settings()
    platform_value = (platform_name or os.name).lower()
    sample = sample or ResourceProbe(settings).sample()
    limits = resolve_worker_limits(
        settings,
        sample,
        platform_name=platform_value,
    )
    python = executable or sys.executable
    common = (
        python,
        "-m",
        "celery",
        "-A",
        "app.workers.celery_app",
        "worker",
        "--loglevel=info",
        "--prefetch-multiplier=1",
    )
    if limits.pool == "solo":
        face_pool = ("--pool=solo", "--concurrency=1")
    else:
        # Passing max=min=1 still starts the custom controller heartbeat while
        # preserving a fixed safe capacity on memory-constrained hosts.
        face_pool = (
            "--pool=prefork",
            f"--autoscale={limits.max_concurrency},{limits.min_concurrency}",
        )
    face_command = common + face_pool + (
        "--hostname=face@%h",
        "--queues=face-v2,celery",
    )
    # Network-bound Drive imports have their own single slot so a slow or
    # rate-limited Google response can never occupy the GPU-facing queue.
    drive_command = common + (
        "--pool=solo",
        "--concurrency=1",
        "--hostname=drive@%h",
        "--queues=drive-downloads",
    )
    return WorkerLaunchPlan(limits, face_command, drive_command)


class _FixedControllerReporter:
    """Emit the agreed controller contract when the pool cannot resize."""

    def __init__(self, plan: WorkerLaunchPlan, probe: ResourceProbe, interval: float):
        self.plan = plan
        self.probe = probe
        self.interval = max(0.5, float(interval))
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="fixed-worker-controller-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _publish(self) -> None:
        sample = self.probe.sample()
        publish_controller_snapshot({
            "autoscale_enabled": False,
            "processing_concurrency": self.plan.limits.min_concurrency,
            "processing_concurrency_min": self.plan.limits.min_concurrency,
            "processing_concurrency_max": self.plan.limits.max_concurrency,
            "processing_control_reason": self.plan.limits.reason,
            "processing_queue_depth": 0,
            "processing_pool": self.plan.limits.pool,
            "autoscale_sample_cpu_percent": sample.cpu_percent,
            "autoscale_sample_gpu_percent": sample.gpu_percent,
            "autoscale_sample_gpu_memory_used_bytes": sample.gpu_memory_used_bytes,
            "autoscale_sample_gpu_memory_total_bytes": sample.gpu_memory_total_bytes,
            "autoscale_gpu_available": sample.gpu_available,
            "autoscale_gpu_index": sample.gpu_index,
            "autoscale_gpu_uuid": sample.gpu_uuid,
            "timestamp": time.time(),
        })

    def _run(self) -> None:
        self._publish()
        while not self.stop_event.wait(self.interval):
            self._publish()


def _spawn(command: tuple[str, ...]) -> subprocess.Popen:
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def _terminate(process: subprocess.Popen, *, force: bool = False) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(
                os.getpgid(process.pid),
                signal.SIGKILL if force else signal.SIGTERM,
            )
        elif force:
            # The Windows venv launcher starts the base interpreter as a child;
            # terminate the complete tree so it cannot outlive the supervisor.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        elif hasattr(signal, "CTRL_BREAK_EVENT"):
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass


def _stop_all(processes: list[subprocess.Popen], grace_seconds: float = 30.0) -> None:
    for process in processes:
        _terminate(process)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _terminate(process, force=True)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def run_supervisor() -> int:
    settings = get_settings()
    probe = ResourceProbe(settings)
    initial_sample = probe.sample()
    plan = build_launch_plan(settings, initial_sample)
    print(
        "Face worker controller: "
        f"pool={plan.limits.pool} autoscale={plan.limits.autoscale_enabled} "
        f"min={plan.limits.min_concurrency} max={plan.limits.max_concurrency} "
        f"reason={plan.limits.reason}",
        flush=True,
    )
    print("Starting face worker: " + " ".join(plan.face_command), flush=True)
    print("Starting Drive worker: " + " ".join(plan.drive_command), flush=True)

    stop_event = threading.Event()
    signal_received = {"value": False}

    def request_stop(_signum, _frame):
        signal_received["value"] = True
        stop_event.set()

    for signal_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, signal_name, None)
        if sig is not None:
            signal.signal(sig, request_stop)

    processes: list[subprocess.Popen] = []
    reporter = None
    try:
        processes.append(_spawn(plan.face_command))
        processes.append(_spawn(plan.drive_command))
        if plan.limits.pool == "solo":
            reporter = _FixedControllerReporter(
                plan,
                probe,
                settings.WORKER_AUTOSCALE_SAMPLE_INTERVAL_SECONDS,
            )
            reporter.start()

        failed_code = None
        while not stop_event.wait(0.5):
            for process in processes:
                code = process.poll()
                if code is not None:
                    failed_code = int(code)
                    print(
                        f"Managed Celery node {process.pid} exited with code {code}; "
                        "stopping its peer.",
                        flush=True,
                    )
                    stop_event.set()
                    break
        if signal_received["value"]:
            return 0
        return failed_code if failed_code not in (None, 0) else 1
    finally:
        if reporter is not None:
            reporter.stop()
        _stop_all(processes)


if __name__ == "__main__":
    raise SystemExit(run_supervisor())
