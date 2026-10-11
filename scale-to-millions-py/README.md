# Scale to Millions (Python)

Python port of the [Node.js version](../scale-to-millions) — a working replica
of the architecture built up across Chapter 1, "Scale From Zero To Millions
of Users," in *System Design Interview* by Alex Xu. Every component the
chapter introduces is a real, independent OS process talking to the others
over localhost HTTP.

Built entirely on the **standard library** (`http.server`, `urllib`,
`threading`, `subprocess`) — no `pip install` required.

## Run it

Requires Python 3.9+.

```
python orchestrator.py
```

Then open **http://127.0.0.1:3000**. Stop everything with `Ctrl+C`.

> Verified live end-to-end: load balancing, write-then-immediate-read showing
> real replication lag, cache-aside hit/miss, async queue processing, and CDN
> static serving all confirmed working.

## Architecture, mapped to the book

Same 9 processes, same ports, as the Node version — see the [Node
README](../scale-to-millions/README.md#architecture-mapped-to-the-book) for
the full table and the "things worth observing" walkthrough (load balancing,
replication lag, cache-aside hit/miss, async queue processing).

## What changed going from Node to Python

- **No framework.** Express hides a lot of HTTP plumbing (routing, JSON
  body/response handling, static file serving). `http.server` gives you
  none of that, so `services/http_util.py` exists purely to avoid
  repeating "parse JSON body" / "send JSON response" in every service —
  the Python equivalent of what Express did for free.
- **Explicit locks.** Node's event loop is single-threaded, so the original
  services never needed to guard shared state (the in-memory user list, WAL,
  cache dict) against concurrent access. `ThreadingHTTPServer` handles each
  connection on its own OS thread, so every service here wraps shared
  mutable state in a `threading.Lock` — skipping that would be a real race
  condition (e.g. two signups landing on the same `next_id`).
- **Fault isolation is different, not better or worse.** In the Node
  version, an uncaught exception in one request handler could crash the
  *entire* process (all connections), which is what happened during testing
  when a bad port choice threw inside a promise. In the threaded Python
  model, an unhandled exception in one request's thread is caught by
  `http.server` internally and logged — it won't take the whole service
  down. Both versions still wrap downstream HTTP calls in `try/except`
  (`try/catch` in Node) to turn a dependency failure into a clean `502`
  instead of a stack trace either way.
- **Static file serving needed one non-obvious fix.** `http.server`'s
  `SimpleHTTPRequestHandler.__init__` resets `self.directory` to
  `os.getcwd()` on every request unless `directory` is passed as a
  constructor kwarg — setting it as a class attribute silently gets
  overwritten. `services/cdn.py` binds it correctly with
  `functools.partial(Handler, directory=PUBLIC_DIR)`, which is the pattern
  the stdlib docs use for exactly this case.
- **`localhost` cost ~2 seconds per hop on this machine.** Every internal
  service URL originally used `http://localhost:PORT`. `urllib`'s DNS
  resolution for `localhost` returned the IPv6 loopback (`::1`) before the
  IPv4 one; nothing was listening on `::1` (servers bind `0.0.0.0`, IPv4
  only) and something in this environment's network stack silently dropped
  that connection attempt instead of refusing it instantly, so every call
  ate the full 2s timeout before falling back to IPv4. A write touches 3+
  services, so that stacked into multi-second requests and load-balancer
  timeouts. Node's `fetch` never hit this because it resolves `localhost`
  differently. Fix: every internal URL now uses `127.0.0.1` explicitly,
  skipping DNS resolution entirely. Browser-facing URLs (the page you open,
  the CDN links inside it) are left as `localhost` since browsers use
  Happy-Eyeballs dual-stack resolution and don't have this problem.
