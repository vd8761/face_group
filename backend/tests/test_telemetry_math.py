import os
import time
import unittest


os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SUPER_ADMIN_PASSWORD", "test-password")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test",
)
os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("R2_BUCKET_NAME", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.telemetry import _aggregate_resource_rows, _rates_from_hash


class RollingRateTests(unittest.TestCase):
    def test_rate_uses_only_current_window(self):
        values = {
            "i:70": "99",
            "f:70": "99",
            "i:99": "2",
            "f:99": "6",
            "i:100": "1",
            "f:100": "3",
        }
        images, faces = _rates_from_hash(
            values,
            now_second=100,
            window_seconds=10,
        )
        self.assertEqual(images, 1.5)
        self.assertEqual(faces, 4.5)

    def test_empty_rate_is_zero(self):
        self.assertEqual(_rates_from_hash({}, now_second=100), (0.0, 0.0))

    def test_rate_parses_bounded_ring_buckets(self):
        images, faces = _rates_from_hash(
            {
                "b:98": "98:4:7",
                "b:99": "99:2:5",
                # An old epoch in a reused slot cannot enter this window.
                "b:1": "1:999:999",
            },
            now_second=100,
            window_seconds=5,
        )
        self.assertEqual(images, 2.0)
        self.assertEqual(faces, 4.0)


class ResourceAggregationTests(unittest.TestCase):
    def test_stale_workers_are_excluded(self):
        resources = _aggregate_resource_rows([
            {
                "component": "worker",
                "timestamp": time.time() - 60,
                "processor": "gpu",
                "cpu_percent": 80,
            }
        ])
        self.assertTrue(resources["stale"])
        self.assertEqual(resources["worker_count"], 0)
        self.assertEqual(resources["processor"], "unknown")

    def test_mixed_workers_and_gpu_hosts_are_aggregated(self):
        now = time.time()
        resources = _aggregate_resource_rows([
            {
                "component": "web",
                "host_id": "api",
                "timestamp": now,
                "processor": "unknown",
                "cpu_percent": 10,
            },
            {
                "component": "worker",
                "host_id": "gpu-host",
                "timestamp": now,
                "processor": "gpu",
                "cpu_percent": 20,
                "gpu_percent": 75,
                "gpu_memory_used_bytes": 4,
                "gpu_memory_total_bytes": 8,
            },
            {
                "component": "worker",
                "host_id": "cpu-host",
                "timestamp": now,
                "processor": "cpu",
                "cpu_percent": 30,
            },
        ])
        self.assertFalse(resources["stale"])
        self.assertEqual(resources["processor"], "mixed")
        self.assertEqual(resources["worker_count"], 2)
        self.assertEqual(resources["cpu_percent"], 20.0)
        self.assertEqual(resources["gpu_percent"], 75.0)

    def test_cpu_is_capacity_weighted_and_same_host_processes_are_summed(self):
        now = time.time()
        resources = _aggregate_resource_rows([
            {"component": "web", "host_id": "a", "timestamp": now,
             "cpu_percent": 20, "cpu_capacity": 2},
            {"component": "worker", "host_id": "a", "timestamp": now,
             "processor": "cpu", "cpu_percent": 30, "cpu_capacity": 2},
            {"component": "worker", "host_id": "b", "timestamp": now,
             "processor": "cpu", "cpu_percent": 100, "cpu_capacity": 1},
        ])
        self.assertEqual(resources["cpu_percent"], 66.7)


if __name__ == "__main__":
    unittest.main()
