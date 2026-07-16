import asyncio
import math
import os
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


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

from app.models import BatchSource  # noqa: E402
from app.services.dispatcher import (  # noqa: E402
    DRIVE_DOWNLOAD_QUEUE,
    DispatchRecord,
    _publish,
)
from app.services.drive_rate_limiter import (  # noqa: E402
    DriveDownloadLimiterUnavailable,
    wait_for_drive_download_slot,
)


class _ScriptedRedis:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _AtomicClockRedis:
    """Small in-memory model of the Lua gate for concurrency tests."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._next_by_key = {}
        self.grants = []

    async def eval(self, _script, _num_keys, key, interval_ms, _ttl_ms):
        async with self._lock:
            now_ms = time.monotonic() * 1000
            next_ms = self._next_by_key.get(key, 0)
            if next_ms > now_ms:
                return [0, math.ceil(next_ms - now_ms)]
            self._next_by_key[key] = now_ms + int(interval_ms)
            self.grants.append(now_ms)
            return [1, 0]


class DriveRateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_twenty_per_minute_uses_three_second_slots(self):
        redis = _ScriptedRedis([[1, 0]])

        await wait_for_drive_download_slot(
            redis_url="redis://unused",
            downloads_per_minute=20,
            redis_client=redis,
        )

        _script, key_count, _key, interval_ms, ttl_ms = redis.calls[0]
        self.assertEqual(key_count, 1)
        self.assertEqual(interval_ms, 3000)
        self.assertGreaterEqual(ttl_ms, 60_000)

    async def test_denied_caller_waits_for_the_owned_slot(self):
        redis = _ScriptedRedis([[0, 250], [1, 0]])
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        await wait_for_drive_download_slot(
            redis_url="redis://unused",
            downloads_per_minute=20,
            redis_client=redis,
            sleep=fake_sleep,
        )

        self.assertEqual(sleeps, [0.25])
        self.assertEqual(len(redis.calls), 2)

    async def test_concurrent_workers_share_one_evenly_spaced_gate(self):
        redis = _AtomicClockRedis()
        # One millisecond slots keep the test fast while exercising many
        # concurrent callers against the same global key.
        await asyncio.gather(*(
            wait_for_drive_download_slot(
                redis_url="redis://unused",
                downloads_per_minute=60_000,
                redis_client=redis,
            )
            for _ in range(12)
        ))

        self.assertEqual(len(redis.grants), 12)
        gaps = [
            right - left
            for left, right in zip(redis.grants, redis.grants[1:])
        ]
        self.assertTrue(all(gap >= 1 for gap in gaps), gaps)

    async def test_redis_failure_never_falls_back_to_an_unpaced_permit(self):
        redis = _ScriptedRedis([TimeoutError("redis unavailable")])

        with self.assertRaises(DriveDownloadLimiterUnavailable):
            await wait_for_drive_download_slot(
                redis_url="redis://unused",
                downloads_per_minute=20,
                redis_client=redis,
            )


class DriveQueueRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_drive_download_is_published_to_dedicated_queue(self):
        record = DispatchRecord(
            item_id=uuid.uuid4(),
            photo_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            source=BatchSource.drive_import,
            source_ref="drive-file-id",
            original_key="",
            claim_token="dispatching:test",
        )

        with (
            patch(
                "app.workers.tasks.import_drive_item.apply_async",
                return_value=SimpleNamespace(id="celery-task-id"),
            ) as apply_async,
            patch(
                "app.services.dispatcher._finish_dispatch_claim",
                new=AsyncMock(),
            ),
        ):
            published = await _publish(record)

        self.assertTrue(published)
        self.assertEqual(apply_async.call_args.kwargs["queue"], DRIVE_DOWNLOAD_QUEUE)
        self.assertEqual(DRIVE_DOWNLOAD_QUEUE, "drive-downloads")


if __name__ == "__main__":
    unittest.main()
