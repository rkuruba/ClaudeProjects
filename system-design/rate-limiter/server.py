"""Demo HTTP server with the limiter as middleware.   python server.py  -> http://127.0.0.1:8000

    curl -i http://127.0.0.1:8000/login            # per-IP rules
    curl -i -H "X-User-Id: bob" http://127.0.0.1:8000/posts
    curl -i -H "X-Api-Key: k1"  http://127.0.0.1:8000/api/data
    curl http://127.0.0.1:8000/metrics
"""
import json
import os
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from limiter import RateLimiter, Request, load_rules_file

HERE = os.path.dirname(os.path.abspath(__file__))
limiter = RateLimiter(load_rules_file(os.path.join(HERE, "rules.json")),
                      retry_queue=queue.Queue(maxsize=1000))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = {f"{r}:{o}": n for (r, o), n in limiter.metrics.items()}
            return self._send(200, {}, body)
        req = Request(self.path, self.client_address[0],
                      self.headers.get("X-User-Id"), self.headers.get("X-Api-Key"))
        res = limiter.check(req)
        if res.allowed:
            self._send(200, res.headers, {"ok": True, "path": self.path})
        else:
            self._send(429, res.headers, {"error": "Too Many Requests", "rule": res.rule})

    def _send(self, status, headers, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print("listening on http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
