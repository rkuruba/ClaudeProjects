"""Message queue (Chapter 1: "Message queue").
Decouples slow/non-critical work (e.g. sending a welcome email) from the
request path. The web tier publishes a job and responds to the user
immediately; a separate worker process consumes and processes it later.
"""
import os          # read PORT from the environment
import sys         # manipulate sys.path so the sibling http_util module can be imported
import threading   # guard the shared queues dict against concurrent access
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # stdlib HTTP server: one thread per connection
from urllib.parse import urlparse, parse_qs  # split the path from the query string, and parse query params

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import send_json, read_json_body  # noqa: E402  # shared JSON request/response helpers

PORT = int(os.environ.get('PORT', 6060))  # which port to listen on; defaults to 6060

lock = threading.Lock()  # protects the queues dict from concurrent publish/consume calls
queues = {}  # topic -> list of jobs; each job is {"payload": ...}


class Handler(BaseHTTPRequestHandler):  # handles one HTTP request; a new instance is created per request
    def log_message(self, fmt, *args):  # override to silence the default per-request access log to stderr
        pass  # do nothing - keeps orchestrator.py's colored log output clean

    def do_GET(self):  # dispatches GET requests based on path
        if self.path == '/health':  # liveness check used by the load balancer / orchestrator
            return send_json(self, 200, {'ok': True})  # simply confirm the process is up

        parsed = urlparse(self.path)  # split self.path into path + query components (only needed below)
        if parsed.path == '/consume':  # this is the endpoint worker.py polls in a loop
            topic = parse_qs(parsed.query).get('topic', [None])[0]  # parse ?topic=X from the query string, defaulting to None
            with lock:  # popping a job must be atomic so two consumers can't grab the same one
                jobs = queues.get(topic)  # look up this topic's job list, if it exists
                if not jobs:  # either the topic doesn't exist yet, or it's currently empty
                    self.send_response(204)  # 204 No Content: "nothing to consume right now"
                    self.end_headers()  # no body follows a 204
                    return  # done - the caller (worker.py) will just poll again later
                job = jobs.pop(0)  # dequeue the oldest job (FIFO)
            return send_json(self, 200, job)  # hand the job back to the consumer

        send_json(self, 404, {'error': 'not found'})  # no route matched this GET path

    def do_POST(self):  # dispatches POST requests based on path
        if self.path == '/publish':  # the only write endpoint this service exposes
            body = read_json_body(self)  # parse the JSON request body, e.g. {"topic": "...", "payload": {...}}
            topic = body.get('topic')  # which queue to publish onto
            payload = body.get('payload')  # the arbitrary job data itself
            if not topic:  # reject a publish with no topic - there'd be nowhere to enqueue it
                return send_json(self, 400, {'error': 'topic is required'})  # 400 Bad Request for invalid input

            with lock:  # appending to (and possibly creating) a topic's list must be atomic
                queues.setdefault(topic, []).append({'payload': payload})  # create the topic's list on first use, then enqueue
                depth = len(queues[topic])  # how many jobs are now waiting on this topic

            print(f'[queue] published to "{topic}": {payload}', flush=True)  # visible confirmation the job was enqueued
            return send_json(self, 202, {'ok': True, 'queueDepth': depth})  # 202 Accepted: queued, not yet processed

        send_json(self, 404, {'error': 'not found'})  # no route matched this POST path


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)  # bind on all interfaces so other processes/machines can reach it
    print(f'[queue] listening on :{PORT}', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    server.serve_forever()  # block forever, dispatching each incoming connection to a new Handler/thread
