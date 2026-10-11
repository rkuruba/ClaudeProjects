"""Load balancer (Chapter 1: "Load balancer").
Distributes incoming traffic round-robin across N stateless web servers,
and stops routing to any server that fails its health check.
"""
import http.client  # low-level HTTP client used to hand-roll the reverse proxy
import os           # read PORT/BACKENDS from the environment
import sys          # manipulate sys.path so the sibling http_util module can be imported
import threading    # background health-check thread + lock around shared backend state
import time         # pace the health-check loop
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # stdlib HTTP server: one thread per connection
from urllib.parse import urlparse  # split a backend URL into hostname/port for http.client

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import send_json, http_json  # noqa: E402  # shared JSON response helper + outbound HTTP client (used for health checks)

PORT = int(os.environ.get('PORT', 3000))  # which port to listen on; defaults to 3000
BACKEND_URLS = os.environ.get('BACKENDS', 'http://127.0.0.1:3001,http://127.0.0.1:3002').split(',')  # comma-separated list of web-tier URLs to balance across

lock = threading.Lock()  # protects backends/next_index from concurrent access across request and health-check threads
backends = [{'url': url, 'healthy': True} for url in BACKEND_URLS]  # start every backend assumed healthy until the first health check says otherwise
next_index = 0  # round-robin cursor into the (filtered) list of healthy backends

HOP_BY_HOP_HEADERS = {'connection', 'transfer-encoding', 'keep-alive', 'proxy-authenticate'}  # headers that must not be blindly forwarded by a proxy


def pick_backend():  # selects the next backend to route a request to, round-robin among healthy ones
    global next_index  # reassigned below, so must be declared global
    with lock:  # reading/filtering backends and advancing next_index must be atomic
        healthy = [b for b in backends if b['healthy']]  # exclude anything the health-check loop has marked down
        if not healthy:  # every backend is currently unhealthy
            return None  # signal "nothing to route to" to the caller
        backend = healthy[next_index % len(healthy)]  # wrap the cursor around the current (possibly shrunk) healthy list
        next_index += 1  # advance the cursor so the next call picks the next backend
        return backend  # the chosen backend dict, e.g. {'url': ..., 'healthy': True}


def check_health():  # runs forever on a background thread, probing each backend
    while True:  # infinite health-check loop
        for backend in backends:  # check every configured backend, healthy or not, so recoveries are detected too
            try:  # a backend being down should not crash this loop
                status, _ = http_json('GET', f'{backend["url"]}/health', timeout=1.5)  # probe its /health endpoint
                backend['healthy'] = status == 200  # mark healthy only on an exact 200 OK
            except Exception:  # connection refused, timeout, etc.
                backend['healthy'] = False  # treat any failure as unhealthy
        time.sleep(5)  # wait 5 seconds before the next full sweep


class Handler(BaseHTTPRequestHandler):  # handles one HTTP request; a new instance is created per request
    def log_message(self, fmt, *args):  # override to silence the default per-request access log to stderr
        pass  # do nothing - keeps orchestrator.py's colored log output clean

    def _proxy(self):  # forwards this request verbatim to a chosen backend and streams its response back
        backend = pick_backend()  # round-robin selection among currently healthy backends
        if backend is None:  # every backend is down
            return send_json(self, 503, {'error': 'No healthy backends available'})  # 503 Service Unavailable: no one to route to

        parsed = urlparse(backend['url'])  # split the backend URL into hostname/port for http.client
        length = int(self.headers.get('Content-Length', 0) or 0)  # how many bytes of request body (if any) to forward
        body = self.rfile.read(length) if length else None  # read the request body only if one was actually sent
        headers = {k: v for k, v in self.headers.items() if k.lower() != 'host'}  # drop the original Host header; http.client sets its own

        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)  # open a fresh connection to the chosen backend
        try:  # the backend could fail mid-request even though its last health check passed
            conn.request(self.command, self.path, body=body, headers=headers)  # forward the same method/path/body/headers as the original request
            res = conn.getresponse()  # wait for and read the backend's response
            payload = res.read()  # read the full response body into memory

            self.send_response(res.status)  # mirror the backend's status code back to the original client
            for key, value in res.getheaders():  # forward the backend's response headers...
                if key.lower() in HOP_BY_HOP_HEADERS:  # ...except connection-specific ones, which don't make sense to relay through a proxy
                    continue  # skip this header
                self.send_header(key, value)  # relay every other header unchanged
            self.send_header('x-load-balancer', 'round-robin')  # marker header so you can see in devtools this response passed through the LB
            self.end_headers()  # blank line marking the end of headers
            self.wfile.write(payload)  # write the backend's response body to the original client
        except Exception:  # the backend dropped the connection, timed out, etc.
            backend['healthy'] = False  # immediately mark it down rather than waiting for the next health-check sweep
            send_json(self, 502, {'error': f'Backend {backend["url"]} unreachable'})  # 502 Bad Gateway: the LB is fine, the backend isn't
        finally:  # always clean up the connection, whether the request succeeded or failed
            conn.close()  # release the socket back to the OS

    do_GET = _proxy     # every HTTP verb this load balancer supports uses the exact same proxying logic
    do_POST = _proxy    # POST needs proxying for writes (e.g. /api/users)
    do_PUT = _proxy     # PUT isn't used by this app today, but is proxied for completeness
    do_DELETE = _proxy  # DELETE isn't used by this app today, but is proxied for completeness


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    threading.Thread(target=check_health, daemon=True).start()  # start probing backends in the background; daemon so it dies with the process
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)  # bind on all interfaces so the browser can reach it
    print(f'[load-balancer] listening on :{PORT}, backends: {", ".join(BACKEND_URLS)}', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    server.serve_forever()  # block forever, dispatching each incoming connection to a new Handler/thread
