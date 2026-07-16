from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.workers.resource_autoscaler import (
    ResourceAwareAutoscaler,
    ResourceSample,
    resolve_worker_limits,
)
from app.workers.supervisor import build_launch_plan


def controller_settings(**overrides):
    values = {
        "WORKER_AUTOSCALE_ENABLED": True,
        "WORKER_AUTOSCALE_MIN_CONCURRENCY": 1,
        "WORKER_AUTOSCALE_MAX_CONCURRENCY": 4,
        "WORKER_AUTOSCALE_CPU_MAX_CONCURRENCY": 1,
        "WORKER_AUTOSCALE_GPU_DEVICE_INDEX": 0,
        "WORKER_AUTOSCALE_GPU_MEMORY_PER_PROCESS_MB": 1800,
        "WORKER_AUTOSCALE_GPU_MEMORY_RESERVE_MB": 1024,
        "WORKER_AUTOSCALE_SYSTEM_MEMORY_PER_PROCESS_MB": 1800,
        "WORKER_AUTOSCALE_SYSTEM_MEMORY_RESERVE_MB": 768,
        "WORKER_AUTOSCALE_GPU_GROW_PERCENT": 72.0,
        "WORKER_AUTOSCALE_CPU_GROW_PERCENT": 75.0,
        "WORKER_AUTOSCALE_CPU_SHRINK_PERCENT": 92.0,
        "WORKER_AUTOSCALE_SAMPLE_INTERVAL_SECONDS": 2.0,
        "WORKER_AUTOSCALE_GROW_SAMPLES": 3,
        "WORKER_AUTOSCALE_SCALE_UP_COOLDOWN_SECONDS": 15.0,
        "WORKER_AUTOSCALE_IDLE_SECONDS": 20.0,
        "WORKER_AUTOSCALE_SCALE_DOWN_COOLDOWN_SECONDS": 30.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def healthy_sample(**overrides):
    values = {
        "cpu_percent": 20.0,
        "cpu_capacity": 8.0,
        "memory_available_bytes": 24 * 1024**3,
        "memory_total_bytes": 32 * 1024**3,
        "gpu_available": True,
        "gpu_index": 0,
        "gpu_uuid": "GPU-test",
        "gpu_percent": 25.0,
        "gpu_memory_used_bytes": 2 * 1024**3,
        "gpu_memory_total_bytes": 12 * 1024**3,
    }
    values.update(overrides)
    return ResourceSample(**values)


class FakeProbe:
    def __init__(self, sample):
        self.value = sample

    def sample(self):
        return self.value


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


class FakePool:
    def __init__(self, processes=1, *, busy=False):
        self.num_processes = processes
        self.busy = busy
        self.maintained = 0

    def grow(self, amount):
        self.num_processes += amount

    def shrink(self, amount):
        if self.busy:
            raise ValueError("all processes busy")
        self.num_processes -= amount

    def maintain_pool(self):
        self.maintained += 1


class ResourceLimitTests(unittest.TestCase):
    def test_windows_always_uses_solo_one(self):
        limits = resolve_worker_limits(
            controller_settings(),
            healthy_sample(),
            platform_name="nt",
        )
        self.assertEqual(limits.pool, "solo")
        self.assertFalse(limits.autoscale_enabled)
        self.assertEqual((limits.min_concurrency, limits.max_concurrency), (1, 1))

    def test_four_gb_gpu_resolves_to_one_model_process(self):
        limits = resolve_worker_limits(
            controller_settings(),
            healthy_sample(gpu_memory_total_bytes=4 * 1024**3),
            platform_name="posix",
        )
        self.assertEqual(limits.max_concurrency, 1)
        self.assertFalse(limits.autoscale_enabled)

    def test_larger_gpu_is_still_bounded_by_hard_max(self):
        limits = resolve_worker_limits(
            controller_settings(WORKER_AUTOSCALE_MAX_CONCURRENCY=3),
            healthy_sample(gpu_memory_total_bytes=24 * 1024**3),
            platform_name="posix",
        )
        self.assertEqual(limits.max_concurrency, 3)
        self.assertTrue(limits.autoscale_enabled)

    def test_missing_nvml_fails_closed_to_cpu_limit(self):
        limits = resolve_worker_limits(
            controller_settings(),
            healthy_sample(gpu_available=False),
            platform_name="posix",
        )
        self.assertEqual(limits.max_concurrency, 1)
        self.assertFalse(limits.autoscale_enabled)


class ResourceAwareAutoscalerTests(unittest.TestCase):
    def make_scaler(self, *, pool=None, sample=None, clock=None, queued=4, settings=None):
        pool = pool or FakePool()
        probe = FakeProbe(sample or healthy_sample())
        clock = clock or FakeClock()
        snapshots = []
        scaler = ResourceAwareAutoscaler(
            pool,
            max_concurrency=4,
            min_concurrency=1,
            settings_override=settings or controller_settings(),
            resource_probe=probe,
            queue_depth=lambda: queued,
            clock=clock,
            publisher=snapshots.append,
            platform_name="posix",
        )
        return scaler, probe, clock, snapshots

    def test_growth_requires_sustained_headroom_and_ramps_one(self):
        scaler, _probe, clock, _snapshots = self.make_scaler()
        clock.value = 20
        scaler.maybe_scale()
        clock.value = 22
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 1)
        clock.value = 24
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 2)
        self.assertEqual(scaler.pool.maintained, 1)

    def test_busy_gpu_blocks_growth(self):
        scaler, _probe, clock, snapshots = self.make_scaler(
            sample=healthy_sample(gpu_percent=95.0)
        )
        clock.value = 20
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 1)
        self.assertEqual(snapshots[-1]["processing_control_reason"], "gpu_busy")

    def test_memory_pressure_shrinks_only_one_idle_child(self):
        pool = FakePool(processes=3)
        scaler, _probe, clock, snapshots = self.make_scaler(
            pool=pool,
            sample=healthy_sample(
                gpu_memory_used_bytes=11_500 * 1024**2,
                gpu_memory_total_bytes=12 * 1024**3,
            ),
            queued=3,
        )
        clock.value = 2
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 2)
        self.assertEqual(snapshots[-1]["processing_control_reason"], "gpu_memory_pressure")

    def test_lost_gpu_metrics_fail_closed_and_shrink_one(self):
        pool = FakePool(processes=3)
        scaler, probe, clock, snapshots = self.make_scaler(pool=pool, queued=3)
        probe.value = healthy_sample(gpu_available=False)
        clock.value = 2
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 2)
        self.assertEqual(
            snapshots[-1]["processing_control_reason"],
            "gpu_metrics_unavailable",
        )

    def test_busy_pool_defers_pressure_shrink(self):
        pool = FakePool(processes=2, busy=True)
        scaler, _probe, clock, snapshots = self.make_scaler(
            pool=pool,
            sample=healthy_sample(memory_available_bytes=256 * 1024**2),
            queued=2,
        )
        clock.value = 2
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 2)
        self.assertEqual(
            snapshots[-1]["processing_control_reason"],
            "pool_busy_cannot_shrink",
        )

    def test_idle_pool_observes_both_idle_and_resize_cooldowns(self):
        pool = FakePool(processes=3)
        scaler, _probe, clock, _snapshots = self.make_scaler(pool=pool, queued=1)
        clock.value = 31
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 3)
        clock.value = 52
        scaler.maybe_scale()
        self.assertEqual(scaler.processes, 2)

    def test_snapshot_uses_websocket_field_contract(self):
        scaler, _probe, clock, snapshots = self.make_scaler()
        clock.value = 20
        scaler.maybe_scale()
        snapshot = snapshots[-1]
        for field in (
            "autoscale_enabled",
            "processing_concurrency",
            "processing_concurrency_min",
            "processing_concurrency_max",
            "processing_control_reason",
            "autoscale_sample_cpu_percent",
            "autoscale_sample_gpu_percent",
        ):
            self.assertIn(field, snapshot)


class WorkerLaunchPlanTests(unittest.TestCase):
    def test_posix_plan_has_adaptive_face_and_isolated_drive_nodes(self):
        plan = build_launch_plan(
            controller_settings(),
            healthy_sample(),
            platform_name="posix",
            executable="python",
        )
        face = " ".join(plan.face_command)
        drive = " ".join(plan.drive_command)
        self.assertIn("--pool=prefork", face)
        self.assertIn("--autoscale=4,1", face)
        self.assertIn("--queues=face-v2,celery", face)
        self.assertIn("--pool=solo", drive)
        self.assertIn("--concurrency=1", drive)
        self.assertIn("--queues=drive-downloads", drive)

    def test_windows_plan_uses_solo_for_both_nodes(self):
        plan = build_launch_plan(
            controller_settings(),
            healthy_sample(),
            platform_name="nt",
            executable="python",
        )
        self.assertIn("--pool=solo", plan.face_command)
        self.assertNotIn("--pool=prefork", plan.face_command)
        self.assertIn("--pool=solo", plan.drive_command)


if __name__ == "__main__":
    unittest.main()
