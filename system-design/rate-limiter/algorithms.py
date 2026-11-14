"""The five rate-limiting algorithms from System Design Interview, ch. 4.

Every algorithm is a pure function of (previous state, current time):

    step(state, now) -> (new_state, Decision)

Keeping them pure means the *store* decides how the read-modify-write is made
atomic (a lock here, a Redis Lua script / MULTI-EXEC in production).
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float = 0.0  # seconds until a retry could succeed (0 if allowed)


class Algorithm(ABC):
    limit: int  # reported in X-Ratelimit-Limit

    @abstractmethod
    def step(self, state: Optional[Any], now: float) -> Tuple[Any, Decision]:
        ...


class TokenBucket(Algorithm):
    """Bucket holds up to `capacity` tokens; `refill_rate` tokens/sec are added.
    Each request consumes one token. Allows bursts up to `capacity`."""

    def __init__(self, capacity: int, refill_rate: float):
        self.limit, self.capacity, self.refill_rate = capacity, capacity, refill_rate

    def step(self, state, now):
        tokens, last = state if state else (float(self.capacity), now)
        tokens = min(self.capacity, tokens + max(0.0, now - last) * self.refill_rate)
        if tokens >= 1:
            tokens -= 1
            return (tokens, now), Decision(True, self.limit, int(tokens))
        wait = (1 - tokens) / self.refill_rate
        return (tokens, now), Decision(False, self.limit, 0, wait)


class LeakingBucket(Algorithm):
    """Requests enter a FIFO queue of size `capacity` that drains at `outflow_rate`/sec.
    Implemented as the 'leaky bucket as a meter': we track the queue level instead of
    holding real requests, which gives the same admit/drop decisions and a smooth,
    fixed outflow rate. A full bucket drops the request."""

    def __init__(self, capacity: int, outflow_rate: float):
        self.limit, self.capacity, self.outflow_rate = capacity, capacity, outflow_rate

    def step(self, state, now):
        level, last = state if state else (0.0, now)
        level = max(0.0, level - max(0.0, now - last) * self.outflow_rate)
        if level + 1 <= self.capacity:
            level += 1
            return (level, now), Decision(True, self.limit, int(self.capacity - level))
        wait = (level + 1 - self.capacity) / self.outflow_rate
        return (level, now), Decision(False, self.limit, 0, wait)


class FixedWindowCounter(Algorithm):
    """Time is cut into fixed windows, each with a counter. Cheap, but a burst
    straddling a window edge can let through up to 2x `limit`."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window

    def step(self, state, now):
        idx = math.floor(now / self.window)
        count = state[1] if state and state[0] == idx else 0
        if count < self.limit:
            count += 1
            return (idx, count), Decision(True, self.limit, self.limit - count)
        retry = (idx + 1) * self.window - now
        return (idx, count), Decision(False, self.limit, 0, retry)


class SlidingWindowLog(Algorithm):
    """Keeps a timestamp per request. As in the book, the new timestamp is added
    *before* checking, so rejected requests stay in the log (and count against
    the client). Exact, but O(limit) memory per key."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window

    def step(self, state, now):
        log: deque = state if state is not None else deque()
        log.append(now)
        cutoff = now - self.window
        while log and log[0] <= cutoff:
            log.popleft()
        size = len(log)
        if size <= self.limit:
            return log, Decision(True, self.limit, self.limit - size)
        # Retry works once the (size - limit)-th oldest entry leaves the window.
        retry = log[size - self.limit - 1] + self.window - now
        return log, Decision(False, self.limit, 0, max(0.0, retry))


class SlidingWindowCounter(Algorithm):
    """Hybrid: estimate = current_count + previous_count * overlap%, where overlap
    is the share of the sliding window that still lies in the previous fixed window.
    The estimate is rounded down, as in the book (3 + 5*70% = 6.5 -> 6). O(1) memory;
    assumes traffic in the previous window was evenly spread."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window

    def step(self, state, now):
        idx = math.floor(now / self.window)
        cur_idx, cur, prev = state if state else (idx, 0, 0)
        if idx != cur_idx:
            prev = cur if idx == cur_idx + 1 else 0  # a gap of >=1 empty window resets
            cur, cur_idx = 0, idx
        elapsed = (now - idx * self.window) / self.window
        estimate = math.floor(cur + prev * (1 - elapsed))
        if estimate < self.limit:
            cur += 1
            return (cur_idx, cur, prev), Decision(True, self.limit, self.limit - estimate - 1)
        retry = (idx + 1) * self.window - now  # upper bound: next window boundary
        return (cur_idx, cur, prev), Decision(False, self.limit, 0, retry)


ALGORITHMS = {
    "token_bucket": TokenBucket,
    "leaking_bucket": LeakingBucket,
    "fixed_window": FixedWindowCounter,
    "sliding_window_log": SlidingWindowLog,
    "sliding_window_counter": SlidingWindowCounter,
}
