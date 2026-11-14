# Scale to Millions

A working (not diagram-only) replica of the architecture built up across
Chapter 1, "Scale From Zero To Millions of Users," in *System Design
Interview* by Alex Xu. Every component the chapter introduces is a real,
independent process talking to the others over localhost HTTP — the same
shape as separate machines on a network, just without needing Docker or
multiple hosts.

## Run it

```
npm install
npm start
```

Then open **http://localhost:3000**. Stop everything with `Ctrl+C` — the
orchestrator kills every child process for you.

## Architecture, mapped to the book

| Service | Port | Chapter 1 concept |
|---|---|---|
| `load-balancer` | 3000 | Load balancer — round-robins across web-1/web-2, drops any instance that fails its health check |
| `web` (×2: web-1, web-2) | 3001, 3002 | Stateless web tier — identical instances, no local state, so either one can serve any request |
| `db-primary` | 5000 | Database primary — accepts all writes, appends each one to a write-ahead log (WAL) |
| `db-replica` | 5001 | Database replica — serves all reads, polls the primary's WAL and applies entries after a simulated lag |
| `cache` | 4000 | Cache — in-memory key/value store standing in for Redis/Memcached, shared by both web instances |
| `cdn` | 7000 | CDN — serves static assets (CSS/JS) from a dedicated server with long-lived cache headers |
| `queue` + `worker` | 6060 | Message queue — decouples slow work (sending a "welcome email") from the request path |

Request flow:

- **Write** (`POST /api/users`): web tier → primary DB (WAL++) → cache invalidated → job published to queue → responds immediately. The worker processes the queued job asynchronously.
- **Read** (`GET /api/users`): web tier checks cache first; on a miss, reads from the **replica** (never the primary) and repopulates the cache.

## Things worth actually observing

1. **Load balancing** — `curl -I http://localhost:3000/health` a few times and watch the `x-served-by` header alternate between `web-1` and `web-2`.
2. **Replication lag** — `POST` a user, then `GET /api/users` immediately: the replica (and the book!) makes no promise the write is visible yet. Wait ~1.2s and it appears. This is the same eventual-consistency behavior real Postgres/MySQL replicas exhibit.
3. **Cache-aside** — the response body includes `"source"`, which flips between `"replica-db"` (cache miss) and `"cache"` (cache hit) depending on whether the 8s TTL has expired.
4. **Async processing** — watch the terminal: `[queue]` logs the publish, then ~0.5-1.3s later `[worker]` logs picking it up and "sending" the welcome email, entirely off the HTTP request path.
5. **CDN offload** — static assets (`style.css`, `app.js`) are served from port 7000 with `Cache-Control: public, max-age=31536000, immutable`, not from the web tier.

## What's simplified vs. a real deployment

- Replication uses HTTP polling of an in-memory WAL, not a real database's binary streaming replication protocol — the *behavior* (async replication with visible lag) is real, the wire protocol isn't.
- The cache, queue, and DBs are single in-memory processes rather than clustered/persistent services — there's no failover if one of them dies.
- Multi-data-center deployment and database sharding (also covered later in Chapter 1) aren't represented here — this focuses on the single-data-center pieces that are runnable as one system.
