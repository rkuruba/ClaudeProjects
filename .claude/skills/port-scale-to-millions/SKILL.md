---
name: port-scale-to-millions
description: Apply a change to the scale-to-millions system across all three implementations (Node in scale-to-millions/, Python in scale-to-millions-py/, Java in scale-to-millions-java/) so they stay behaviorally identical, then run each one to verify. Use whenever the user asks to add, change, fix, or remove a service, endpoint, env var, port, or behavior in any scale-to-millions variant, or asks to sync/port a change between them.
---

# Port a change across scale-to-millions variants

The three directories are ports of one system (Node → Python → Java). They must keep the **same 9 processes, ports, env vars, HTTP routes, JSON shapes, and timing behavior**. A change that lands in only one variant is incomplete unless the user explicitly scopes it to one.

## 1. Locate the change in all three

Service file mapping:

| Service | Node (`scale-to-millions/`) | Python (`scale-to-millions-py/`) | Java (`scale-to-millions-java/`) |
|---|---|---|---|
| orchestrator | `orchestrator.js` | `orchestrator.py` | `Orchestrator.java` |
| shared helpers | — (Express + `fetch`) | `services/http_util.py` | `services/HttpUtil.java`, `services/Json.java` |
| cache :4000 | `services/cache/index.js` | `services/cache.py` | `services/CacheService.java` |
| db-primary :5000 | `services/db-primary/index.js` | `services/db_primary.py` | `services/DbPrimary.java` |
| db-replica :5001 | `services/db-replica/index.js` | `services/db_replica.py` | `services/DbReplica.java` |
| queue :6060 | `services/queue/index.js` | `services/queue.py` | `services/QueueService.java` |
| cdn :7000 | `services/cdn/index.js` | `services/cdn.py` | `services/Cdn.java` |
| worker (no port) | `services/worker/index.js` | `services/worker.py` | `services/Worker.java` |
| web-1/web-2 :3001/:3002 | `services/web/index.js` | `services/web.py` | `services/Web.java` |
| load-balancer :3000 | `services/load-balancer/index.js` | `services/load_balancer.py` | `services/LoadBalancer.java` |

Static assets (`frontend/index.html`, `public-cdn/app.js`, `public-cdn/style.css`) are **separate copies per variant**. Frontend changes must be made in all three copies.

Read the corresponding file in every variant before editing. They are parallel but not line-for-line identical.

## 2. Translate idioms, not syntax

| Concern | Node | Python | Java |
|---|---|---|---|
| Routing | Express `app.get/post(...)` | `do_GET`/`do_POST` with `if self.path == ...` | one `createContext("/")` handler that branches on `method` + `path` |
| JSON in/out | `express.json()`, `res.json()` | `read_json_body`, `send_json` from `http_util` | `HttpUtil.readJsonBody`, `HttpUtil.sendJson` (built on `Json.parse`/`Json.encode`; no JSON library, don't add one) |
| Outbound HTTP | `fetch` | `http_json(method, url, payload)` → `(status, body)` | `HttpUtil.httpJson(...)` → `HttpResult` record |
| Shared mutable state | no lock (single event loop) | wrap in `threading.Lock` | wrap in `ReentrantLock` |
| Delayed callback | `setTimeout` | `threading.Timer` | daemon `java.util.Timer` |
| Background loop | `setInterval` / async loop | daemon `threading.Thread` | daemon `Thread` |
| Env var | `process.env.X \|\| default` | `os.environ.get('X', default)` | `System.getenv().getOrDefault("X", default)` |
| Fixed-shape data | object literal | tuple/dict | `record` |

Rules that differ between variants and are easy to get wrong:

- **Internal URLs:** Node uses `http://localhost:PORT`. Python and Java **must** use `http://127.0.0.1:PORT`, because `localhost` resolved to IPv6 first on this machine and cost about 2 s per hop. Browser-facing URLs stay `localhost`.
- **Locks:** any new shared state touched by request handlers or background threads needs a lock in Python and Java, even though the Node version has none.
- **Dependencies:** Python and Java are stdlib-only. Never add pip packages, Maven/Gradle, or external JARs. Node may use what's in `package.json` (currently only Express).
- **Failure tolerance:** startup order is not enforced. Any new call to another service must survive that service being down (catch the error, return 502 or retry on the next poll); it must never crash the process.
- **New service, port, or env var:** add it to all three orchestrators' service lists (`services` array / `SERVICES` list / `SERVICES` `List.of`) with identical names, ports, and env keys. For Java, the class must be in package `services`; the orchestrator compiles every `.java` file under the project automatically.

## 3. Match each variant's comment style

- **Python:** almost every line carries an inline `#` comment explaining it, plus a module docstring. New Python code must follow that density.
- **Node and Java:** sparse comments, mostly a header comment per file and one block comment above each non-obvious handler.

Keep the explanations equivalent across variants, just at each file's own density.

## 4. Update docs

- If behavior, ports, or routes change, update the README tables in the affected variants.
- `scale-to-millions-py/ARCHITECTURE.md` cites **Python line numbers** (e.g. `web.py:57`, `orchestrator.py:16-38`). After editing Python files, re-check every `file.py:N` reference in that doc and fix any that shifted.
- If a variant now does something differently for a language-specific reason, add a bullet to that README's "What changed going from …" section.

## 5. Verify each variant end to end

All three bind the same ports, so run them **one at a time** and make sure the previous one is fully stopped (port 3000 refuses connections) before starting the next.

Start each variant from its own directory as a background task:

```bash
cd scale-to-millions && npm install && npm start
cd scale-to-millions-py && python orchestrator.py
cd scale-to-millions-java && java Orchestrator.java   # must run from this directory; compiles into out/ first
```

Give it a few seconds (Java needs longer because of `javac`), then exercise it:

```bash
curl -s -i http://127.0.0.1:3000/health | grep -i x-served-by       # repeat: alternates web-1 / web-2
curl -s -X POST -H "Content-Type: application/json" -d '{"name":"Ada"}' http://127.0.0.1:3000/api/users
curl -s http://127.0.0.1:3000/api/users                              # immediately: user may be missing (replication lag is intended)
curl -s http://127.0.0.1:3000/api/users                              # after ~1.5 s: user present; "source" shows replica-db or cache
```

Also check the orchestrator's log output for `[worker]` processing the `user.created` job, and exercise whatever the change itself added. The same requests must produce the same status codes and JSON shapes in all three variants.

Stop the variant, then confirm nothing still listens on ports 3000–7000 before starting the next one. If a port is still held, find the leftover process by port and stop it; don't just pick a different port.

## 6. Report

Tell the user which files changed in each variant, and what was verified in each. Name any variant that couldn't be run (e.g. JDK missing) rather than implying it was tested.
