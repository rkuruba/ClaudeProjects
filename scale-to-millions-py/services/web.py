"""Stateless web tier (Chapter 1: "Stateless web tier").
Holds NO local state - every request can be handled by any instance, which
is exactly what makes horizontal scaling behind the load balancer possible.
All state lives in the cache and database services.
"""
import os          # read PORT/NODE_ID/downstream URLs from the environment
import sys         # manipulate sys.path so the sibling http_util module can be imported
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # stdlib HTTP server: one thread per connection

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import send_json, read_json_body, http_json  # noqa: E402  # shared response/body helpers + outbound HTTP client

PORT = int(os.environ.get('PORT', 3001))  # which port to listen on; defaults to 3001
NODE_ID = os.environ.get('NODE_ID', f'web-{PORT}')  # identifies which instance served a response, for observability
CACHE_URL = os.environ.get('CACHE_URL', 'http://127.0.0.1:4000')  # where the cache service lives
PRIMARY_URL = os.environ.get('PRIMARY_URL', 'http://127.0.0.1:5000')  # where the write-capable primary DB lives
REPLICA_URL = os.environ.get('REPLICA_URL', 'http://127.0.0.1:5001')  # where the read-only replica DB lives
QUEUE_URL = os.environ.get('QUEUE_URL', 'http://127.0.0.1:6060')  # where the message queue lives
CDN_URL = os.environ.get('CDN_URL', 'http://127.0.0.1:7000')  # where static assets are served from

FRONTEND_HTML = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')  # path to the single HTML page this tier serves


class Handler(BaseHTTPRequestHandler):  # handles one HTTP request; a new instance is created per request
    def log_message(self, fmt, *args):  # override to silence the default per-request access log to stderr
        pass  # do nothing - keeps orchestrator.py's colored log output clean

    def _send(self, status, payload):  # thin wrapper around send_json that always tags the response with this node's id
        send_json(self, status, payload, extra_headers={'x-served-by': NODE_ID})  # lets clients see which web instance answered

    def do_GET(self):  # dispatches GET requests based on path
        if self.path == '/health':  # polled by the load balancer's health-check loop
            return self._send(200, {'ok': True, 'node': NODE_ID})  # confirm this instance is up, and which one it is

        if self.path == '/config.json':  # tells the browser where to fetch static assets from
            return self._send(200, {'cdnUrl': CDN_URL, 'servedBy': NODE_ID})  # the browser then talks to the CDN directly, bypassing this tier

        if self.path == '/':  # serve the single-page frontend
            with open(FRONTEND_HTML, 'rb') as f:  # open in binary mode since we're writing raw bytes to the socket
                body = f.read()  # read the whole file into memory (it's small, so no streaming needed)
            self.send_response(200)  # write the status line
            self.send_header('Content-Type', 'text/html')  # tell the browser to render this as HTML
            self.send_header('Content-Length', str(len(body)))  # tell the browser exactly how many bytes to expect
            self.send_header('x-served-by', NODE_ID)  # same node-id marker as _send, for consistency
            self.end_headers()  # blank line marking the end of headers
            return self.wfile.write(body)  # write the HTML bytes to the response socket

        if self.path == '/api/users':  # the read endpoint for the user list
            return self._get_users()  # delegate to the method implementing the cache-aside pattern

        self._send(404, {'error': 'not found'})  # no route matched this GET path

    def _get_users(self):  # implements the cache-aside read pattern
        # Read path: cache-aside. Check cache first; on miss, read from the
        # REPLICA (never the primary) and repopulate the cache.
        try:  # any downstream call (cache or replica) could fail; turn that into a clean 502 instead of a stack trace
            cache_status, cached = http_json('GET', f'{CACHE_URL}/cache/users:all')  # ask the cache for the precomputed user list
            if cache_status == 200:  # cache hit
                return self._send(200, {'source': 'cache', 'node': NODE_ID, 'users': cached['value']})  # serve straight from cache, no DB touched

            _, users = http_json('GET', f'{REPLICA_URL}/users')  # cache miss - fall back to the read replica, never the primary
            http_json('PUT', f'{CACHE_URL}/cache/users:all', {'value': users, 'ttlMs': 8000})  # repopulate the cache so the next read hits
            return self._send(200, {'source': 'replica-db', 'node': NODE_ID, 'users': users})  # tell the caller this came from the DB, not cache
        except Exception as err:  # cache or replica unreachable, timed out, etc.
            print(f'[web:{NODE_ID}] downstream failure on GET /api/users: {err}', flush=True)  # log the failure for debugging
            self._send(502, {'error': 'A downstream service is unavailable'})  # 502 Bad Gateway: this tier is fine, a dependency isn't

    def do_POST(self):  # dispatches POST requests based on path
        if self.path == '/api/users':  # the only write endpoint this tier exposes
            return self._create_user()  # delegate to the method implementing the write + invalidate + publish sequence
        self._send(404, {'error': 'not found'})  # no route matched this POST path

    def _create_user(self):  # implements the write path: primary DB, then cache invalidation, then async job
        # Write path: always goes to the PRIMARY. Invalidates the cache so
        # the next read isn't stale, and publishes an event so slow
        # follow-up work (sending a welcome email) happens asynchronously
        # instead of blocking this response.
        try:  # any downstream call (primary, cache, or queue) could fail; turn that into a clean 502 instead of a stack trace
            body = read_json_body(self)  # parse the incoming JSON, e.g. {"name": "Alice"}
            primary_status, user = http_json('POST', f'{PRIMARY_URL}/users', body)  # forward the write straight to the primary DB
            if primary_status >= 400:  # the primary rejected the write (e.g. missing name)
                return self._send(primary_status, user)  # pass the primary's error status/body straight through to the client

            http_json('DELETE', f'{CACHE_URL}/cache/users:all')  # invalidate the stale cached list now that the DB has changed
            http_json('POST', f'{QUEUE_URL}/publish', {  # publish a job for the worker to process later, off this request's critical path
                'topic': 'user.created',
                'payload': {'id': user['id'], 'name': user['name']},
            })

            self._send(201, {'node': NODE_ID, 'user': user})  # 201 Created - respond to the client without waiting on the queued job
        except Exception as err:  # primary, cache, or queue unreachable, timed out, etc.
            print(f'[web:{NODE_ID}] downstream failure on POST /api/users: {err}', flush=True)  # log the failure for debugging
            self._send(502, {'error': 'A downstream service is unavailable'})  # 502 Bad Gateway: this tier is fine, a dependency isn't


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)  # bind on all interfaces so the load balancer can reach it
    print(f'[web:{NODE_ID}] listening on :{PORT}', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    server.serve_forever()  # block forever, dispatching each incoming connection to a new Handler/thread
