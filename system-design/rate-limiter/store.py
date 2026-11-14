"""Shared counter store - the stand-in for Redis.

The book's distributed-environment challenges are *race conditions* (two servers
read the same counter, both write +1) and *synchronization* (many limiter
instances must see the same counters). The fix it recommends is an atomic
read-modify-write against a centralized store. `update` is that primitive:
in Redis it would be a Lua script or MULTI/EXEC; here it is a striped lock.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Tuple


class InMemoryStore:
    def __init__(self, stripes: int = 64):
        self._data: Dict[str, Any] = {}
        self._locks = [threading.Lock() for _ in range(stripes)]  # per-key-ish, not global

    def update(self, key: str, fn: Callable[[Any], Tuple[Any, Any]]) -> Any:
        """Atomically: state = get(key); new_state, result = fn(state); set(key, new_state)."""
        with self._locks[hash(key) % len(self._locks)]:
            new_state, result = fn(self._data.get(key))
            self._data[key] = new_state
            return result
