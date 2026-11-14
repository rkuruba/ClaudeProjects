"""Rate limiter middleware: rules, identities, headers, hard/soft limits, queueing, metrics."""
from __future__ import annotations

import json
import math
import queue
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

from algorithms import ALGORITHMS, Algorithm, Decision
from store import InMemoryStore


@dataclass
class Request:
    path: str
    ip: str
    user_id: Optional[str] = None
    api_key: Optional[str] = None


@dataclass
class Rule:
    """One throttling rule, like the YAML rules the book shows (Lyft's limiter).

    key_by: which identity is throttled - "ip", "user_id", "api_key", or "global".
    hard:   True  -> over-limit requests are rejected (429).
            False -> soft limit: requests may exceed it, but are flagged/counted.
    """
    name: str
    algorithm: Algorithm
    key_by: str = "ip"
    path_prefix: str = "/"
    hard: bool = True


@dataclass
class Result:
    status: int  # 200 or 429
    headers: Dict[str, str]
    rule: Optional[str] = None  # rule that drove the headers / the rejection

    @property
    def allowed(self) -> bool:
        return self.status == 200


def load_rules(configs: Iterable[dict]) -> List[Rule]:
    """Build rules from plain dicts, e.g. parsed from JSON in a rules store/cache."""
    rules = []
    for c in configs:
        algo = ALGORITHMS[c["algorithm"]](**c.get("params", {}))
        rules.append(Rule(c["name"], algo, c.get("key_by", "ip"),
                          c.get("path_prefix", "/"), c.get("hard", True)))
    return rules


def load_rules_file(path: str) -> List[Rule]:
    with open(path, encoding="utf-8") as f:
        return load_rules(json.load(f))


class RateLimiter:
    def __init__(self, rules: List[Rule], store: Optional[InMemoryStore] = None,
                 clock: Callable[[], float] = time.time,
                 exempt: Iterable[str] = (),
                 retry_queue: Optional["queue.Queue[Request]"] = None):
        self.rules = rules
        self.store = store or InMemoryStore()
        self.clock = clock
        self.exempt = set(exempt)       # identities (ip/user/key) that bypass limiting
        self.retry_queue = retry_queue  # rate-limited requests can be parked for later
        self.metrics: Counter = Counter()

    @staticmethod
    def _identity(rule: Rule, req: Request) -> Optional[str]:
        return "*" if rule.key_by == "global" else getattr(req, rule.key_by, None)

    def check(self, req: Request) -> Result:
        if self.exempt & {req.ip, req.user_id, req.api_key}:
            return Result(200, {})

        now = self.clock()
        decisions: List[tuple] = []  # (rule, decision)
        for rule in self.rules:
            if not req.path.startswith(rule.path_prefix):
                continue
            ident = self._identity(rule, req)
            if ident is None:  # e.g. a per-user rule on an anonymous request
                continue
            d: Decision = self.store.update(f"{rule.name}:{ident}",
                                            lambda s, a=rule.algorithm: a.step(s, now))
            decisions.append((rule, d))

        if not decisions:
            return Result(200, {})

        # Hard-denied rules reject the request; soft-denied ones only flag it.
        hard_denied = [(r, d) for r, d in decisions if not d.allowed and r.hard]
        soft_denied = [(r, d) for r, d in decisions if not d.allowed and not r.hard]
        for r, _ in soft_denied:
            self.metrics[(r.name, "soft_exceeded")] += 1

        if hard_denied:
            # Report the rule that makes the client wait longest.
            rule, d = max(hard_denied, key=lambda rd: rd[1].retry_after)
            self.metrics[(rule.name, "dropped")] += 1
            if self.retry_queue is not None:
                try:
                    self.retry_queue.put_nowait(req)
                except queue.Full:
                    pass  # queue full -> request is simply dropped
            return Result(429, {
                "X-Ratelimit-Limit": str(d.limit),
                "X-Ratelimit-Remaining": "0",
                "X-Ratelimit-Retry-After": str(max(1, math.ceil(d.retry_after))),
                "Retry-After": str(max(1, math.ceil(d.retry_after))),
            }, rule.name)

        # Allowed: advertise the tightest remaining quota across applicable rules.
        rule, d = min(decisions, key=lambda rd: rd[1].remaining)
        for r, _ in decisions:
            self.metrics[(r.name, "allowed")] += 1
        headers = {"X-Ratelimit-Limit": str(d.limit),
                   "X-Ratelimit-Remaining": str(d.remaining)}
        if soft_denied:
            headers["X-Ratelimit-Soft-Exceeded"] = ",".join(r.name for r, _ in soft_denied)
        return Result(200, headers, rule.name)
