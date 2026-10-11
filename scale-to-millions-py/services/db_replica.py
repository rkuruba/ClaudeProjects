"""Read replica (Chapter 1: "Database replication" - slave node).
Serves ALL reads so the primary is freed up to handle writes. Polls the
primary's WAL and applies entries with a deliberate delay to make
replication lag visible - a write to the primary is not guaranteed to be
immediately visible on a replica, exactly as the book calls out.
"""
import os          # read PORT/PRIMARY_URL/REPLICATION_LAG_MS from the environment
import sys         # manipulate sys.path so the sibling http_util module can be imported
import threading   # background polling thread + lock around shared state
import time        # sleep between poll cycles
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # stdlib HTTP server: one thread per connection

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import send_json, http_json  # noqa: E402  # shared response helper + outbound HTTP client

PORT = int(os.environ.get('PORT', 5001))  # which port to listen on; defaults to 5001
PRIMARY_URL = os.environ.get('PRIMARY_URL', 'http://127.0.0.1:5000')  # where to fetch the WAL from
REPLICATION_LAG_MS = int(os.environ.get('REPLICATION_LAG_MS', 1200))  # artificial delay before applying a WAL entry

lock = threading.Lock()   # protects users/last_applied_seq from concurrent access
users = []                 # this replica's own copy of the "table", built up from applied WAL entries
last_applied_seq = 0       # highest WAL sequence number applied so far (also used as the next poll's `since`)


def apply_entry(entry):  # applies a single WAL entry to this replica's local state
    if entry['type'] == 'insert':  # this project only ever produces insert entries, but the check keeps it explicit
        with lock:  # mutating `users` must be atomic with respect to concurrent readers
            users.append(entry['row'])  # replay the insert locally
        print(f'[db-replica] applied WAL seq={entry["seq"]} -> user#{entry["row"]["id"]} '  # log line proving replication happened
              f'(lag={REPLICATION_LAG_MS}ms)', flush=True)  # and reminding you how much delay was injected


def poll_primary():  # runs forever on a background thread, tailing the primary's WAL
    global last_applied_seq  # reassigned below, so must be declared global
    while True:  # infinite polling loop - this is the whole replication mechanism
        try:  # the primary might be down or slow to start; don't let that kill this thread
            status, entries = http_json('GET', f'{PRIMARY_URL}/wal?since={last_applied_seq}', timeout=2)  # ask for anything newer than what we've seen
            if status == 200 and entries:  # only proceed if the call succeeded and there's actually new data
                for entry in entries:  # there may be multiple new writes since the last poll
                    threading.Timer(REPLICATION_LAG_MS / 1000, apply_entry, args=[entry]).start()  # schedule the apply after the artificial lag (ms -> seconds)
                    last_applied_seq = max(last_applied_seq, entry['seq'])  # advance our watermark immediately so we don't re-fetch this entry next poll
        except Exception:  # any network failure (primary down, timeout, etc.)
            pass  # primary unreachable this cycle; retry next tick
        time.sleep(0.5)  # wait half a second before polling again


class Handler(BaseHTTPRequestHandler):  # handles one HTTP request; a new instance is created per request
    def log_message(self, fmt, *args):  # override to silence the default per-request access log to stderr
        pass  # do nothing - keeps orchestrator.py's colored log output clean

    def do_GET(self):  # dispatches GET requests based on path
        if self.path == '/health':  # liveness check used by the load balancer / orchestrator
            return send_json(self, 200, {'ok': True})  # simply confirm the process is up

        if self.path == '/users':  # this is the endpoint web.py reads from on a cache miss
            with lock:  # snapshot users under the lock so we don't read a half-mutated list
                return send_json(self, 200, list(users))  # copy the list before returning so callers can't mutate our internal state

        if self.path == '/status':  # exposes replication health for debugging/observability
            return send_json(self, 200, {
                'lastAppliedSeq': last_applied_seq,       # how far behind the primary's WAL we've caught up to
                'replicationLagMs': REPLICATION_LAG_MS,   # the configured artificial delay
            })

        send_json(self, 404, {'error': 'not found'})  # no route matched this GET path


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    threading.Thread(target=poll_primary, daemon=True).start()  # start tailing the primary in the background; daemon so it dies with the process
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)  # bind on all interfaces so other processes/machines can reach it
    print(f'[db-replica] listening on :{PORT}, tailing {PRIMARY_URL}', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    server.serve_forever()  # block forever, dispatching each incoming connection to a new Handler/thread
