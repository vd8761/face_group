"""Redis-authoritative pacing for Google Drive media downloads.

Celery rate limits are local to a worker process, so they cannot protect a
shared Google API key when several workers or organizations are active.  This
gate uses Redis server time and a single global next-slot key.  It deliberately
has no burst capacity: each successful caller is separated from the next by a
full interval.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any, Awaitable, Callable, Optional


DRIVE_DOWNLOAD_RATE_KEY = "pg:drive-downloads:global:v1"

# Redis TIME avoids clock skew between worker hosts.  SET is performed only by
# the permit winner, so callers that are told to wait do not extend the queue.
_ACQUIRE_SLOT_LUA = """
local redis_time = redis.call('TIME')
local now_ms = (tonumber(redis_time[1]) * 1000) + math.floor(tonumber(redis_time[2]) / 1000)
local interval_ms = tonumber(ARGV[1])
local ttl_ms = tonumber(ARGV[2])
local next_ms = tonumber(redis.call('GET', KEYS[1]) or '0')

if next_ms > now_ms then
  return {0, next_ms - now_ms}
end

redis.call('SET', KEYS[1], now_ms + interval_ms, 'PX', ttl_ms)
return {1, 0}
"""


class DriveDownloadLimiterUnavailable(RuntimeError):
    """The global gate cannot safely decide whether a download may start."""


_redis_client: Optional[Any] = None
_redis_client_url: Optional[str] = None


def _get_redis_client(redis_url: str) -> Any:
    """Return one loop-safe client per Celery worker process."""
    global _redis_client, _redis_client_url
    if _redis_client is None or _redis_client_url != redis_url:
        from redis.asyncio import Redis

        _redis_client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        _redis_client_url = redis_url
    return _redis_client


async def wait_for_drive_download_slot(
    *,
    redis_url: str,
    downloads_per_minute: int,
    redis_client: Optional[Any] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    key: str = DRIVE_DOWNLOAD_RATE_KEY,
) -> None:
    """Wait until this caller atomically owns the next global download slot.

    A Redis error is never treated as a permit.  Callers receive a dedicated
    transient exception so the durable batch item can be released and retried
    without eventually becoming a permanent failure.
    """
    try:
        rate = int(downloads_per_minute)
    except (TypeError, ValueError) as exc:
        raise DriveDownloadLimiterUnavailable(
            "Drive download rate is not a valid integer"
        ) from exc
    if rate < 1:
        raise DriveDownloadLimiterUnavailable(
            "Drive download rate must be at least one per minute"
        )

    interval_ms = max(1, int(math.ceil(60_000 / rate)))
    # Preserve the next slot through ordinary worker restarts and short idle
    # periods.  Expiry prevents an obsolete/corrupt key from blocking forever.
    ttl_ms = max(60_000, interval_ms * 4)
    client = redis_client or _get_redis_client(redis_url)

    while True:
        try:
            result = await client.eval(
                _ACQUIRE_SLOT_LUA,
                1,
                key,
                interval_ms,
                ttl_ms,
            )
            allowed = int(result[0])
            wait_ms = max(0, int(result[1]))
        except Exception as exc:
            raise DriveDownloadLimiterUnavailable(
                "Drive download pacing is temporarily unavailable"
            ) from exc

        if allowed == 1:
            return
        if wait_ms <= 0:
            # A malformed response must not accidentally turn into a permit.
            raise DriveDownloadLimiterUnavailable(
                "Drive download pacing returned an invalid wait interval"
            )
        await sleep(wait_ms / 1000.0)


def reset_drive_rate_limiter_client() -> None:
    """Drop the cached client (used by worker lifecycle hooks and tests)."""
    global _redis_client, _redis_client_url
    _redis_client = None
    _redis_client_url = None
