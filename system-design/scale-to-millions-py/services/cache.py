"""Cache tier (Chapter 1: "Cache").
Stands in for Redis/Memcached: a fast in-memory key-value store, separate
from the web tier, so multiple stateless web servers share one cache instead
of each holding its own.
"""
import os          # read PORT from the environment
import sys         # manipulate sys.path so the sibling http_util module can be imported
import threading   # guard the shared store/stats dicts against concurrent access
import time        # compute and check key expiry timestamps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # stdlib HTTP server: one thread per connection

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import send_json, read_json_body  # noqa: E402  # shared JSON request/response helpers

PORT = int(os.environ.get('PORT', 4000))  # which port to listen on; defaults to 4000

store = {}  # key -> (value, expires_at); expires_at is a unix timestamp
stats = {'hits': 0, 'misses': 0}  # running counters exposed via /stats
lock = threading.Lock()  # protects store/stats from concurrent access across request threads


class Handler(BaseHTTPRequestHandler):  # handles one HTTP request; a new instance is created per request
    def log_message(self, fmt, *args):  # override to silence the default per-request access log to stderr
        pass  # do nothing - keeps orchestrator.py's colored log output clean

    def do_GET(self):  # dispatches GET requests based on path
        if self.path == '/health':  # liveness check used by the load balancer / orchestrator
            return send_json(self, 200, {'ok': True})  # simply confirm the process is up

        if self.path == '/stats':  # exposes hit/miss counters for debugging/observability
            with lock:  # snapshot stats/store size under the lock for a consistent read
                return send_json(self, 200, {**stats, 'keys': len(store)})  # merge counters with the current key count

        if self.path.startswith('/cache/'):  # e.g. GET /cache/users:all
            key = self.path[len('/cache/'):]  # strip the "/cache/" prefix to get the raw key
            with lock:  # the read-check-evict sequence below must be atomic
                entry = store.get(key)  # look up the (value, expires_at) tuple, if present
                if not entry or entry[1] < time.time():  # missing entirely, or its TTL has already passed
                    store.pop(key, None)  # lazily evict an expired entry (no-op if it was never there)
                    stats['misses'] += 1  # record this as a miss
                    return send_json(self, 404, {'hit': False})  # 404 signals "not in cache" to the caller
                stats['hits'] += 1  # entry exists and hasn't expired - record a hit
                return send_json(self, 200, {'hit': True, 'value': entry[0]})  # return just the value, not the internal expiry

        send_json(self, 404, {'error': 'not found'})  # no route matched this GET path

    def do_PUT(self):  # dispatches PUT requests - used to write/overwrite a cache entry
        if self.path.startswith('/cache/'):  # e.g. PUT /cache/users:all
            key = self.path[len('/cache/'):]  # strip the "/cache/" prefix to get the raw key
            body = read_json_body(self)  # parse the JSON request body, e.g. {"value": [...], "ttlMs": 8000}
            ttl_ms = body.get('ttlMs', 10000)  # how long this entry should live; default 10s if not specified
            with lock:  # writing to the shared dict must be atomic
                store[key] = (body.get('value'), time.time() + ttl_ms / 1000)  # store the value alongside its absolute expiry time (ms -> seconds)
            return send_json(self, 200, {'ok': True})  # confirm the write succeeded
        send_json(self, 404, {'error': 'not found'})  # no route matched this PUT path

    def do_DELETE(self):  # dispatches DELETE requests - used to invalidate a cache entry
        if self.path.startswith('/cache/'):  # e.g. DELETE /cache/users:all
            key = self.path[len('/cache/'):]  # strip the "/cache/" prefix to get the raw key
            with lock:  # removing from the shared dict must be atomic
                store.pop(key, None)  # remove the key if present; no error if it wasn't there
            return send_json(self, 200, {'ok': True})  # confirm the delete succeeded (idempotent either way)
        send_json(self, 404, {'error': 'not found'})  # no route matched this DELETE path


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)  # bind on all interfaces so other processes/machines can reach it
    print(f'[cache] listening on :{PORT}', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    server.serve_forever()  # block forever, dispatching each incoming connection to a new Handler/thread
