import queue
import threading
import unittest

from algorithms import (FixedWindowCounter, LeakingBucket, SlidingWindowCounter,
                        SlidingWindowLog, TokenBucket)
from limiter import RateLimiter, Request, Rule, load_rules
from store import InMemoryStore


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def run(algo, times):
    """Feed request times to one key; return list of allowed booleans."""
    store, out = InMemoryStore(), []
    for t in times:
        out.append(store.update("k", lambda s, t=t: algo.step(s, t)).allowed)
    return out


class AlgorithmTests(unittest.TestCase):
    def test_token_bucket_burst_then_refill(self):
        algo = TokenBucket(capacity=4, refill_rate=1)  # 1 token / sec
        self.assertEqual(run(algo, [0, 0, 0, 0, 0]), [True] * 4 + [False])
        self.assertEqual(run(algo, [0, 0, 0, 0, 0, 1, 1]), [True] * 4 + [False, True, False])

    def test_token_bucket_never_exceeds_capacity(self):
        algo = TokenBucket(capacity=2, refill_rate=1)
        self.assertEqual(run(algo, [0, 1000, 1000, 1000]), [True, True, True, False])

    def test_leaking_bucket_drops_when_full_and_drains(self):
        algo = LeakingBucket(capacity=3, outflow_rate=1)
        self.assertEqual(run(algo, [0, 0, 0, 0]), [True, True, True, False])
        self.assertEqual(run(algo, [0, 0, 0, 0, 2]), [True, True, True, False, True])

    def test_fixed_window_resets_each_window(self):
        algo = FixedWindowCounter(limit=2, window=60)
        self.assertEqual(run(algo, [1, 2, 3, 61, 62, 63]), [True, True, False, True, True, False])

    def test_fixed_window_edge_burst_flaw(self):
        # Book: a burst around the window edge passes 2x the limit...
        algo = FixedWindowCounter(limit=5, window=60)
        self.assertEqual(sum(run(algo, [59.0] * 5 + [61.0] * 5)), 10)

    def test_sliding_log_blocks_edge_burst(self):
        # ...while the sliding window log enforces the limit in any 60s span.
        algo = SlidingWindowLog(limit=5, window=60)
        self.assertEqual(sum(run(algo, [59.0] * 5 + [61.0] * 5)), 5)

    def test_sliding_log_book_example(self):
        # limit 2/min: rejected 1:00:50 stays in the log, 1:01:40 still allowed.
        algo = SlidingWindowLog(limit=2, window=60)
        times = [1, 30, 50, 100]  # seconds after 1:00:00
        self.assertEqual(run(algo, times), [True, True, False, True])

    def test_sliding_counter_book_example(self):
        # limit 7/min; prev window had 5, current has 3, 30% into window:
        # 3 + 5*70% = 6.5 -> 6 < 7 -> allowed.
        algo = SlidingWindowCounter(limit=7, window=60)
        times = [10.0] * 5 + [75.0] * 3 + [78.0]
        self.assertEqual(run(algo, times)[-1], True)
        # One more at the same instant: estimate 4 + 3.5 -> 7, not < 7 -> rejected.
        self.assertEqual(run(algo, times + [78.0])[-1], False)

    def test_sliding_counter_gap_resets_previous(self):
        algo = SlidingWindowCounter(limit=2, window=60)
        self.assertEqual(run(algo, [1, 2, 3, 500, 501, 502]),
                         [True, True, False, True, True, False])

    def test_retry_after_is_actionable(self):
        store = InMemoryStore()
        for algo in (TokenBucket(1, 0.5), LeakingBucket(1, 0.5), FixedWindowCounter(1, 10),
                     SlidingWindowLog(1, 10), SlidingWindowCounter(1, 10)):
            with self.subTest(algo=type(algo).__name__):
                key = type(algo).__name__
                store.update(key, lambda s: algo.step(s, 0.0))
                d = store.update(key, lambda s: algo.step(s, 0.0))
                self.assertFalse(d.allowed)
                self.assertGreater(d.retry_after, 0)


class LimiterTests(unittest.TestCase):
    def make(self, rules, **kw):
        self.clock = Clock()
        return RateLimiter(rules, clock=self.clock, **kw)

    def test_429_and_headers(self):
        lim = self.make([Rule("r", FixedWindowCounter(2, 60))])
        req = Request("/", "1.1.1.1")
        r1, r2, r3 = lim.check(req), lim.check(req), lim.check(req)
        self.assertEqual((r1.status, r1.headers["X-Ratelimit-Remaining"]), (200, "1"))
        self.assertEqual(r2.headers["X-Ratelimit-Remaining"], "0")
        self.assertEqual(r3.status, 429)
        self.assertEqual(r3.headers["X-Ratelimit-Limit"], "2")
        self.assertEqual(r3.headers["X-Ratelimit-Retry-After"], "60")

    def test_clients_are_isolated(self):
        lim = self.make([Rule("r", FixedWindowCounter(1, 60))])
        self.assertTrue(lim.check(Request("/", "a")).allowed)
        self.assertTrue(lim.check(Request("/", "b")).allowed)
        self.assertFalse(lim.check(Request("/", "a")).allowed)

    def test_path_scoped_rules(self):
        lim = self.make([Rule("login", FixedWindowCounter(1, 60), path_prefix="/login")])
        self.assertTrue(lim.check(Request("/login", "a")).allowed)
        self.assertFalse(lim.check(Request("/login", "a")).allowed)
        for _ in range(5):
            self.assertTrue(lim.check(Request("/home", "a")).allowed)

    def test_key_by_user_and_api_key(self):
        lim = self.make([Rule("u", FixedWindowCounter(1, 60), key_by="user_id"),
                         Rule("k", FixedWindowCounter(1, 60), key_by="api_key")])
        self.assertTrue(lim.check(Request("/", "ip1", user_id="bob")).allowed)
        self.assertFalse(lim.check(Request("/", "ip2", user_id="bob")).allowed)   # same user, new IP
        self.assertTrue(lim.check(Request("/", "ip1", user_id="amy", api_key="K")).allowed)
        self.assertFalse(lim.check(Request("/", "ip1", user_id="zed", api_key="K")).allowed)

    def test_anonymous_skips_user_rule(self):
        lim = self.make([Rule("u", FixedWindowCounter(1, 60), key_by="user_id")])
        for _ in range(3):
            self.assertTrue(lim.check(Request("/", "ip")).allowed)

    def test_multiple_rules_all_must_pass(self):
        lim = self.make([Rule("ip", FixedWindowCounter(10, 60)),
                         Rule("user", FixedWindowCounter(1, 60), key_by="user_id")])
        req = Request("/", "ip", user_id="bob")
        self.assertTrue(lim.check(req).allowed)
        res = lim.check(req)
        self.assertEqual((res.status, res.rule), (429, "user"))

    def test_soft_limit_allows_but_flags(self):
        lim = self.make([Rule("soft", FixedWindowCounter(1, 60), hard=False)])
        lim.check(Request("/", "a"))
        res = lim.check(Request("/", "a"))
        self.assertTrue(res.allowed)
        self.assertEqual(res.headers["X-Ratelimit-Soft-Exceeded"], "soft")
        self.assertEqual(lim.metrics[("soft", "soft_exceeded")], 1)

    def test_exempt_identities_bypass(self):
        lim = self.make([Rule("r", FixedWindowCounter(1, 60))], exempt={"10.0.0.1"})
        for _ in range(5):
            self.assertTrue(lim.check(Request("/", "10.0.0.1")).allowed)

    def test_dropped_requests_can_be_queued(self):
        q = queue.Queue(maxsize=1)
        lim = self.make([Rule("r", FixedWindowCounter(1, 60))], retry_queue=q)
        lim.check(Request("/", "a"))
        lim.check(Request("/x", "a"))
        lim.check(Request("/y", "a"))  # queue full -> silently dropped
        self.assertEqual(q.qsize(), 1)
        self.assertEqual(q.get().path, "/x")
        self.assertEqual(lim.metrics[("r", "dropped")], 2)

    def test_recovers_after_window(self):
        lim = self.make([Rule("r", TokenBucket(1, 1))])
        self.assertTrue(lim.check(Request("/", "a")).allowed)
        self.assertFalse(lim.check(Request("/", "a")).allowed)
        self.clock.t = 1.0
        self.assertTrue(lim.check(Request("/", "a")).allowed)

    def test_load_rules_from_config(self):
        rules = load_rules([{"name": "n", "algorithm": "token_bucket",
                             "params": {"capacity": 3, "refill_rate": 1}, "key_by": "ip"}])
        self.assertIsInstance(rules[0].algorithm, TokenBucket)


class DistributedTests(unittest.TestCase):
    def test_shared_store_no_race_across_servers(self):
        """Many 'servers' (limiter instances) + threads share one atomic store:
        exactly `limit` requests may pass, never more."""
        store, clock = InMemoryStore(), Clock(5.0)
        servers = [RateLimiter([Rule("r", FixedWindowCounter(50, 60))], store=store, clock=clock)
                   for _ in range(4)]
        results, lock = [], threading.Lock()

        def worker(i):
            ok = servers[i % 4].check(Request("/", "same-client")).allowed
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(400)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(results), 50)

    def test_token_bucket_concurrent_exact(self):
        store = InMemoryStore()
        algo, results, lock = TokenBucket(20, 0.0001), [], threading.Lock()

        def worker():
            d = store.update("k", lambda s: algo.step(s, 0.0))
            with lock:
                results.append(d.allowed)

        threads = [threading.Thread(target=worker) for _ in range(200)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(results), 20)


if __name__ == "__main__":
    unittest.main()
