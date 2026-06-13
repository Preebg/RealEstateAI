"""Async token-bucket rate limiter keyed by host."""

from __future__ import annotations

import asyncio
import time


class AsyncTokenBucket:
    """Simple per-host async rate limiter."""

    def __init__(self, *, rate: float, capacity: float) -> None:
        self._rate = max(rate, 0.1)
        self._capacity = max(capacity, 1.0)
        self._tokens = self._capacity
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._updated_at = now
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._rate,
                )
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_sec = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait_sec)


class HostRateLimiter:
    """Lazy per-host token buckets."""

    def __init__(self, *, rate: float = 1.0, capacity: float = 2.0) -> None:
        self._rate = rate
        self._capacity = capacity
        self._buckets: dict[str, AsyncTokenBucket] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, host: str) -> None:
        async with self._lock:
            bucket = self._buckets.get(host)
            if bucket is None:
                bucket = AsyncTokenBucket(rate=self._rate, capacity=self._capacity)
                self._buckets[host] = bucket
        await bucket.acquire()
