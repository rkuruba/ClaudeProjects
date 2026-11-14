"""Async worker (Chapter 1: "Message queue" - the consumer side).
Polls the queue and processes jobs off the request path. Simulates sending a
"welcome email" whenever a new user signs up - the canonical message-queue
example from the book.
"""
import os          # read QUEUE_URL from the environment
import sys         # manipulate sys.path so the sibling http_util module can be imported
import time        # simulate slow work, and pace the polling loop

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import http_json  # noqa: E402  # outbound HTTP client used to talk to the queue service

QUEUE_URL = os.environ.get('QUEUE_URL', 'http://127.0.0.1:6060')  # where the queue service lives
TOPIC = 'user.created'  # the only topic this worker knows how to consume


def poll():  # a single poll-and-process cycle, called in a loop below
    try:  # the queue might be down or temporarily unreachable; don't let that crash the worker
        status, job = http_json('GET', f'{QUEUE_URL}/consume?topic={TOPIC}', timeout=2)  # ask the queue for the next job on this topic
        if status != 200 or not job:  # 204 (empty) or any failure means there's nothing to do right now
            return  # nothing to process this cycle - just return and let the loop sleep/retry

        print(f'[worker] processing job: {job["payload"]}', flush=True)  # log that we picked up a job
        time.sleep(0.8)  # simulate slow work, e.g. calling a third-party email API
        print(f'[worker] sent welcome email to "{job["payload"]["name"]}"', flush=True)  # log that the simulated work finished
    except Exception:  # any network failure (queue down, timeout, etc.)
        pass  # queue unreachable this cycle; retry next tick


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    print(f'[worker] polling {QUEUE_URL} for topic "{TOPIC}"', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    while True:  # this process has no HTTP server of its own - it's a pure background poller
        poll()  # attempt to consume and process one job
        time.sleep(0.5)  # wait half a second before polling again
