"""Primary database (Chapter 1: "Database replication" - master node).
Accepts ALL writes. Every write is appended to a write-ahead log (WAL) that
the replica polls, exactly like Postgres/MySQL streaming replication - just
implemented over plain HTTP instead of a binary replication protocol.
"""
import os          # read PORT from the environment
import sys         # manipulate sys.path so the sibling http_util module can be imported
import threading   # guard shared in-memory state against concurrent request threads
import time        # timestamp WAL entries
from datetime import datetime, timezone            # timestamp each created row in ISO format, UTC
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # stdlib HTTP server: one thread per connection
from urllib.parse import urlparse, parse_qs        # split the path from the query string, and parse query params

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import send_json, read_json_body  # noqa: E402  # shared JSON request/response helpers

PORT = int(os.environ.get('PORT', 5000))  # which port to listen on; defaults to 5000 if not set by the orchestrator

lock = threading.Lock()  # protects users/next_id/wal/seq from concurrent access across request threads
users = []       # in-memory "table": list of {id, name, createdAt} dicts
next_id = 1      # auto-incrementing primary key for the next inserted row
wal = []         # write-ahead log: list of {seq, type, row, ts} entries the replica tails
seq = 0          # monotonically increasing sequence number identifying WAL position


class Handler(BaseHTTPRequestHandler):  # handles one HTTP request; a new instance is created per request
    def log_message(self, fmt, *args):  # override to silence the default per-request access log to stderr
        pass  # do nothing - keeps orchestrator.py's colored log output clean

    def do_GET(self):  # dispatches GET requests based on path
        parsed = urlparse(self.path)  # split self.path into path + query components

        if parsed.path == '/health':  # liveness check used by the load balancer / orchestrator
            return send_json(self, 200, {'ok': True})  # simply confirm the process is up

        if parsed.path == '/users':  # full user list, mainly for debugging/inspection
            with lock:  # snapshot users under the lock so we don't read a half-mutated list
                return send_json(self, 200, list(users))  # copy the list before returning so callers can't mutate our internal state

        if parsed.path == '/wal':  # replication feed: "give me every WAL entry after `since`"
            since = int(parse_qs(parsed.query).get('since', ['0'])[0])  # parse ?since=N from the query string, defaulting to 0
            with lock:  # snapshot wal under the lock for the same reason as /users
                return send_json(self, 200, [e for e in wal if e['seq'] > since])  # only entries newer than what the caller already has

        send_json(self, 404, {'error': 'not found'})  # no route matched this GET path

    def do_POST(self):  # dispatches POST requests based on path
        global next_id, seq  # both are mutated below, so must be declared global to assign to them

        if self.path == '/users':  # the only write endpoint this service exposes
            body = read_json_body(self)  # parse the JSON request body, e.g. {"name": "Alice"}
            name = body.get('name')  # extract the required field
            if not name:  # reject empty/missing names
                return send_json(self, 400, {'error': 'name is required'})  # 400 Bad Request for invalid input

            with lock:  # the whole read-modify-write sequence must be atomic across threads
                row = {'id': next_id, 'name': name, 'createdAt': datetime.now(timezone.utc).isoformat()}  # build the new row
                next_id += 1  # advance the primary key counter for the next insert
                users.append(row)  # commit the row into the in-memory "table"
                seq += 1  # advance the WAL sequence number
                wal.append({'seq': seq, 'type': 'insert', 'row': row, 'ts': time.time()})  # record this write in the WAL for replication
                current_seq = seq  # capture the seq value now, before releasing the lock, for the log line below

            print(f'[db-primary] WRITE user#{row["id"]} "{row["name"]}" (wal seq={current_seq})', flush=True)  # visible confirmation the write landed
            return send_json(self, 201, row)  # 201 Created, echoing back the new row (including its assigned id)

        send_json(self, 404, {'error': 'not found'})  # no route matched this POST path


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)  # bind on all interfaces so other processes/machines can reach it
    print(f'[db-primary] listening on :{PORT}', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    server.serve_forever()  # block forever, dispatching each incoming connection to a new Handler/thread
