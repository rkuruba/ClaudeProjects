# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo is a workspace of **independent, unrelated projects** sharing one git history — there is no root build, root `package.json`, or shared code between them. Always `cd` into the relevant subproject before running commands. Subprojects may have their own CLAUDE.md (e.g. `future-me/CLAUDE.md`) — read it when working there.

| Directory | What it is | Stack |
|---|---|---|
| `scale-to-millions/` | Working replica of *System Design Interview* ch. 1 (LB, stateless web ×2, primary/replica DB, cache, CDN, queue+worker) as 9 real processes over localhost HTTP | Node (ESM) + Express |
| `scale-to-millions-py/` | Python port of the above | Python 3.9+ stdlib only |
| `scale-to-millions-java/` | Java port of the Python port | JDK 17+ stdlib only, no Maven/Gradle |
| `color-explorer/` | Color palette explorer: Express API + static frontend | Node (CommonJS) + Express |
| `future-me/` | Static "letter to your future self" page, localStorage only | Vanilla HTML/CSS/JS, no build |
| `faker-next/` | Vendored copy of the upstream `@faker-js/faker` library | TypeScript, pnpm, vitest |
| `HelloWorld.java` | Standalone scratch file | Java |

## Commands

```bash
# scale-to-millions (Node) — open http://localhost:3000
cd scale-to-millions && npm install && npm start

# scale-to-millions-py — open http://127.0.0.1:3000
cd scale-to-millions-py && python orchestrator.py

# scale-to-millions-java — compiles services/ into out/ via javac itself, then spawns them
cd scale-to-millions-java && java Orchestrator.java

# color-explorer — PORT env var overrides the default 3000
cd color-explorer && npm start

# future-me — no build; open index.html or serve statically
cd future-me && npx serve .
```

All three scale-to-millions variants and color-explorer default to port 3000, so only run one at a time. None of the non-faker projects have tests or linters configured.

### faker-next (pnpm; Node version in `.nvmrc`)

```bash
pnpm install
pnpm run test                         # vitest (watch mode)
pnpm vitest run test/modules/string.spec.ts   # single test file
pnpm vitest run -t "fromCharacters"           # tests matching a name
pnpm run test:update-snapshots        # vitest run -u
pnpm run lint                         # eslint
pnpm run ts-check                     # tsc
pnpm run build                        # tsdown
pnpm run preflight                    # generate + format + lint + build + snapshots + ts-check
```

## Architecture notes

### scale-to-millions (all three variants)

- The three directories implement **the same system**: same 9 processes, same ports (LB 3000, web-1/web-2 3001/3002, cache 4000, db-primary 5000, db-replica 5001, queue 6060, CDN 7000, plus a portless worker), same env-var wiring, same request flow. Lineage is Node → Python → Java; each README has a "what changed" section explaining language-specific differences. Behavioral changes usually belong in all three.
- `scale-to-millions-py/ARCHITECTURE.md` is the canonical walkthrough of the invocation graph and request flow, and also applies to the Java port.
- The orchestrator spawns every service as a separate OS process wired together by env vars (`CACHE_URL`, `PRIMARY_URL`, `REPLICA_URL`, `QUEUE_URL`, `CDN_URL`, ...). Services never import each other; in Python/Java they share only an HTTP/JSON helper (`http_util.py` / `HttpUtil.java` + `Json.java`).
- Writes go web → primary (appends a WAL entry) → cache key invalidated → job published to queue. Reads go web → cache → (on miss) **replica, never the primary**. The replica polls the primary's `/wal?since=N` and applies entries after a deliberate `REPLICATION_LAG_MS` (default 1200 ms), so stale reads right after a write are intended behavior, not a bug.
- **Startup order is not enforced.** Services launch near-simultaneously; correctness relies on every consumer (replica poller, worker, LB health check) retrying forever and swallowing connection errors. Keep new dependencies tolerant of the dependency being down.
- Python/Java services are multi-threaded, so all shared mutable state is guarded by a lock (`threading.Lock` / `ReentrantLock`). The Node version doesn't need locks (single event loop); keep this in mind when porting changes.
- Internal service-to-service URLs in the Python/Java versions use `127.0.0.1`, not `localhost`. On this machine, `localhost` resolved to IPv6 `::1` first and each hop lost about 2 s. Browser-facing URLs stay `localhost`.
- Each variant keeps its own copies of `frontend/` and `public-cdn/`; nothing is shared across directories.

### color-explorer

`server.js` serves `public/` statically and exposes `GET /api/colors` (palette from `data/colors.js`, enriched with RGB/HSL computed server-side) and `GET/POST /api/recent`. Recently viewed colors are persisted by rewriting `data/recent.json` on disk (capped at 5), so that file changes during normal use.

### faker-next

Upstream faker-js; follow `faker-next/CONTRIBUTING.md`. Key points:
- Generators live in `src/modules/*` and mostly read per-locale *definitions* from `src/locales/*`. After adding or changing locale data, run `pnpm run generate:locales` to regenerate the derived files.
- Tests in `test/modules/*.spec.ts` use `seededTests(...)` (deterministic, snapshot-based; review snapshot diffs carefully) plus loops of random-seeded runs.
- JSDoc on public methods is parsed by `generate:api-docs` and must follow the conventions in CONTRIBUTING.md. Deprecations call the internal `deprecated()` helper and add `@deprecated` and `@see` tags.

## Repo hygiene

Compiled Java output (`*.class`, `scale-to-millions-java/out/`) and every project's `node_modules/` are gitignored. Run `npm install` / `pnpm install` before starting a Node project in a fresh clone.
