"""Boots every service that makes up the system, each as its own OS process
communicating over localhost HTTP - the same shape as separate machines
talking over a network, just without needing Docker or multiple hosts.
"""
import os          # build filesystem paths, and merge env vars for each child process
import subprocess  # spawn each service as an independent OS process
import sys         # locate the current Python interpreter to re-invoke for each service
import threading   # stream each child process's stdout without blocking the others

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # absolute path to this file's directory (the project root)
SERVICES_DIR = os.path.join(BASE_DIR, 'services')  # where all the individual service scripts live

COLORS = ['\033[36m', '\033[35m', '\033[33m', '\033[32m', '\033[34m', '\033[91m', '\033[92m', '\033[94m', '\033[95m']  # ANSI color codes, one per service, cycled if there are more services than colors
RESET = '\033[0m'  # ANSI code to reset terminal color back to default after each colored prefix

SERVICES = [  # (display name, script filename, env var overrides) for every process to launch
    ('cache', 'cache.py', {'PORT': '4000'}),  # standalone - no downstream dependencies
    ('db-primary', 'db_primary.py', {'PORT': '5000'}),  # standalone - no downstream dependencies
    ('db-replica', 'db_replica.py', {'PORT': '5001', 'PRIMARY_URL': 'http://127.0.0.1:5000'}),  # needs to know where the primary is, to tail its WAL
    ('queue', 'queue.py', {'PORT': '6060'}),  # standalone - no downstream dependencies
    ('cdn', 'cdn.py', {'PORT': '7000'}),  # standalone - no downstream dependencies
    ('worker', 'worker.py', {'QUEUE_URL': 'http://127.0.0.1:6060'}),  # no PORT - this process has no HTTP server, just a poller
    ('web-1', 'web.py', {  # first stateless web instance
        'PORT': '3001', 'NODE_ID': 'web-1',  # its own port and a human-readable identity for logs/headers
        'CACHE_URL': 'http://127.0.0.1:4000', 'PRIMARY_URL': 'http://127.0.0.1:5000',  # where to read/write cache and DB
        'REPLICA_URL': 'http://127.0.0.1:5001', 'QUEUE_URL': 'http://127.0.0.1:6060',  # where to read replicated data and publish jobs
        'CDN_URL': 'http://127.0.0.1:7000',  # told to the browser via /config.json
    }),
    ('web-2', 'web.py', {  # second stateless web instance - identical wiring, different port/id
        'PORT': '3002', 'NODE_ID': 'web-2',  # proves any instance can serve any request (statelessness)
        'CACHE_URL': 'http://127.0.0.1:4000', 'PRIMARY_URL': 'http://127.0.0.1:5000',  # same shared downstream services as web-1
        'REPLICA_URL': 'http://127.0.0.1:5001', 'QUEUE_URL': 'http://127.0.0.1:6060',  # both web instances share one cache/DB/queue, never their own
        'CDN_URL': 'http://127.0.0.1:7000',  # same CDN as web-1
    }),
    ('load-balancer', 'load_balancer.py', {  # the single entry point clients actually connect to
        'PORT': '3000', 'BACKENDS': 'http://127.0.0.1:3001,http://127.0.0.1:3002',  # the pool of web instances to round-robin across
    }),
]

processes = []  # holds the subprocess.Popen handle for every launched service, so main() can wait/terminate them later


def stream_output(name, color, pipe):  # runs on its own thread per service, relaying that service's stdout to this process's stdout
    for line in iter(pipe.readline, ''):  # keep reading lines until the pipe is closed (readline returns '')
        if line.strip():  # skip blank lines so the combined log isn't full of empty rows
            print(f'{color}[{name}]{RESET} {line.rstrip()}', flush=True)  # prefix with a colored service name so interleaved logs stay readable


def main():  # entry point: launches every configured service and waits on them
    for i, (name, script, env_overrides) in enumerate(SERVICES):  # walk the SERVICES list in order, tracking index for color assignment
        color = COLORS[i % len(COLORS)]  # cycle through the palette if there are more services than colors
        env = {**os.environ, **env_overrides}  # start from this process's own environment, then layer the service-specific overrides on top
        proc = subprocess.Popen(  # launch the service as an independent child process
            [sys.executable, os.path.join(SERVICES_DIR, script)],  # run it with the same Python interpreter that's running this orchestrator
            env=env, cwd=SERVICES_DIR,  # pass the merged environment, and run from the services directory (relevant for relative paths like FRONTEND_HTML)
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # capture stdout, and merge stderr into the same stream so nothing is missed
            text=True, bufsize=1,  # decode output as text, and flush line-by-line rather than block-buffering
        )
        processes.append(proc)  # remember this handle so it can be waited on / terminated later
        threading.Thread(target=stream_output, args=(name, color, proc.stdout), daemon=True).start()  # start relaying this service's output concurrently with the others

    print('\nAll services starting. Once ready, open http://127.0.0.1:3000\n', flush=True)  # tell the user where to point their browser

    try:  # let Ctrl+C trigger a graceful shutdown of every child process
        for proc in processes:  # wait on each process in turn
            proc.wait()  # blocks until that particular service exits (normally this never happens, since they serve_forever())
    except KeyboardInterrupt:  # the user pressed Ctrl+C while waiting above
        print('\nShutting down all services...', flush=True)  # let the user know shutdown is in progress
        for proc in processes:  # signal every child process to stop
            proc.terminate()  # send a termination signal (SIGTERM on Unix, TerminateProcess on Windows)
        for proc in processes:  # give every process a chance to actually exit
            proc.wait()  # block until this process has fully terminated before moving to the next


if __name__ == '__main__':  # only runs when executed directly, not if ever imported
    main()  # kick off launching and supervising every service
