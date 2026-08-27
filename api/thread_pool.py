"""Lazy thread pools — no worker threads until the first analysis job."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

_pools: dict[str, ThreadPoolExecutor] = {}
_lock = threading.Lock()


def get_pool(name: str, *, max_workers: int = 2) -> ThreadPoolExecutor:
    with _lock:
        pool = _pools.get(name)
        if pool is None:
            pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)
            _pools[name] = pool
        return pool
