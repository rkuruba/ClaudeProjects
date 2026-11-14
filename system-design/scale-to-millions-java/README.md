# Scale to Millions (Java)

A Java port of the [Python version](../scale-to-millions-py) (itself a port
of the [Node.js version](../scale-to-millions)) - a working replica of the
architecture built up across Chapter 1, "Scale From Zero To Millions of
Users," in *System Design Interview* by Alex Xu. Every component the
chapter introduces is a real, independent OS process talking to the others
over localhost HTTP.

Built entirely on the **JDK standard library** -
`com.sun.net.httpserver.HttpServer` for every service, `java.net.http.HttpClient`
for outbound calls, and a small hand-rolled JSON codec (`services/Json.java`)
instead of a JSON library. No Maven, no Gradle, no external dependencies.

## Run it

Requires a **JDK 17+** (not JRE-only) - `java` and `javac` both need to be
on your PATH. (JDK 17 for records and pattern-matching `instanceof`;
`java.net.http.HttpClient` itself only needs JDK 11.)

```
java Orchestrator.java
```

`Orchestrator.java` shells out to `javac` to compile every service into
`out/` the moment it starts, then spawns each one as its own process - so
this is still a single command, the same "just run it" experience as the
Python version's `python orchestrator.py`.

Then open **http://127.0.0.1:3000**. Stop everything with `Ctrl+C` (a JVM
shutdown hook terminates every child process).

## Architecture, mapped to the Python version

Same 9 processes, same ports, same env-var wiring as
[`../scale-to-millions-py`](../scale-to-millions-py) - see that project's
`ARCHITECTURE.md` for the full invocation graph and request-by-request
walkthrough. Every step is identical here, just with a Java class standing
in for each Python module:

| Python                      | Java                                             |
|------------------------------|---------------------------------------------------|
| `orchestrator.py`            | `Orchestrator.java`                                |
| `services/http_util.py`      | `services/HttpUtil.java` + `services/Json.java`    |
| `services/db_primary.py`     | `services/DbPrimary.java`                          |
| `services/db_replica.py`     | `services/DbReplica.java`                          |
| `services/queue.py`          | `services/QueueService.java`                       |
| `services/cache.py`          | `services/CacheService.java`                       |
| `services/cdn.py`            | `services/Cdn.java`                                |
| `services/worker.py`         | `services/Worker.java`                             |
| `services/web.py`            | `services/Web.java`                                |
| `services/load_balancer.py`  | `services/LoadBalancer.java`                       |

This project is self-contained, same as the other two: `frontend/` and
`public-cdn/` are this project's own copies of the static assets (not
shared across directories), and `Web.java`/`Cdn.java` resolve them relative
to their own project root, exactly as `web.py`/`cdn.py` do in the Python
version.

## What changed going from Python to Java

- **No JSON library.** Python's stdlib ships `json`; Java's doesn't ship an
  equivalent. `services/Json.java` is a ~200-line hand-rolled encoder/decoder
  (`Map`/`List`/`String`/`Number`/`Boolean`/`null`) so the project can stay
  dependency-free instead of pulling in Gson/Jackson.
- **`java.net.http.HttpClient` instead of `urllib`.** Added in JDK 11, it's
  the modern stdlib HTTP client and, like Python's `urllib`, does *not*
  throw on a non-2xx response - only on a real network failure - so
  `HttpUtil.httpJson` mirrors `http_util.py`'s `http_json` almost exactly,
  returning `(status, body)` either way.
- **`com.sun.net.httpserver.HttpServer` instead of `http.server`.** Both are
  minimal stdlib HTTP servers with no routing framework; every service here
  registers one handler for `/` and dispatches on path + method manually,
  the same as the Python `BaseHTTPRequestHandler` subclasses do with
  `do_GET`/`do_POST`.
- **Locks, same as the Python port.** Every service that mutates shared
  state (the primary's WAL, the cache's store, the queue's job lists) wraps
  it in a `ReentrantLock`, since `HttpServer`'s executor - a cached thread
  pool here - handles requests concurrently, just like Python's
  `ThreadingHTTPServer`.
- **An explicit compile step.** Python and Node both run source directly;
  Java needs bytecode first. `Orchestrator.java` calls `javac` itself before
  spawning any service, so the one-command experience is preserved instead
  of asking you to build separately.
- **`threading.Timer` becomes `java.util.Timer`/`TimerTask`.**
  `db_replica.py`'s artificial replication-lag delay uses Python's
  `threading.Timer`; `DbReplica.java` schedules the same delayed callback
  with a daemon `java.util.Timer`.
- **Records instead of dicts/tuples for fixed shapes.** Where Python reaches
  for a dict or tuple for something like an HTTP result or a service spec,
  Java uses a `record` (e.g. `HttpUtil.HttpResult`, `Orchestrator.ServiceSpec`)
  - a compact, immutable, type-checked equivalent.
