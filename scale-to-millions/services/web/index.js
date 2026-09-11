// Stateless web tier (Chapter 1: "Stateless web tier").
// Holds NO local state - every request can be handled by any instance,
// which is exactly what makes horizontal scaling behind the load balancer
// possible. All state lives in the cache and database services.
import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT = process.env.PORT || 3001;
const NODE_ID = process.env.NODE_ID || `web-${PORT}`;
const CACHE_URL = process.env.CACHE_URL || 'http://localhost:4000';
const PRIMARY_URL = process.env.PRIMARY_URL || 'http://localhost:5000';
const REPLICA_URL = process.env.REPLICA_URL || 'http://localhost:5001';
const QUEUE_URL = process.env.QUEUE_URL || 'http://localhost:6060';
const CDN_URL = process.env.CDN_URL || 'http://localhost:7000';

const app = express();
app.use(express.json());

app.use((_req, res, next) => {
  res.setHeader('x-served-by', NODE_ID);
  next();
});

app.get('/health', (_req, res) => res.json({ ok: true, node: NODE_ID }));

app.get('/', (_req, res) => {
  res.sendFile(path.join(__dirname, '..', '..', 'frontend', 'index.html'));
});

app.get('/config.json', (_req, res) => {
  // Lets the static frontend know where the CDN is without hardcoding it.
  res.json({ cdnUrl: CDN_URL, servedBy: NODE_ID });
});

// Read path: cache-aside. Check cache first; on miss, read from the REPLICA
// (never the primary) and repopulate the cache.
app.get('/api/users', async (_req, res) => {
  try {
    const cacheKey = 'users:all';

    const cacheRes = await fetch(`${CACHE_URL}/cache/${cacheKey}`);
    if (cacheRes.status === 200) {
      const { value } = await cacheRes.json();
      return res.json({ source: 'cache', node: NODE_ID, users: value });
    }

    const dbRes = await fetch(`${REPLICA_URL}/users`);
    const users = await dbRes.json();

    await fetch(`${CACHE_URL}/cache/${cacheKey}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: users, ttlMs: 8000 }),
    });

    res.json({ source: 'replica-db', node: NODE_ID, users });
  } catch (err) {
    console.error(`[web:${NODE_ID}] downstream failure on GET /api/users: ${err.message}`);
    res.status(502).json({ error: 'A downstream service is unavailable' });
  }
});

// Write path: always goes to the PRIMARY. Invalidates the cache so the next
// read isn't stale, and publishes an event so slow follow-up work (sending a
// welcome email) happens asynchronously instead of blocking this response.
app.post('/api/users', async (req, res) => {
  try {
    const primaryRes = await fetch(`${PRIMARY_URL}/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
    });

    if (!primaryRes.ok) {
      return res.status(primaryRes.status).json(await primaryRes.json());
    }
    const user = await primaryRes.json();

    await fetch(`${CACHE_URL}/cache/users:all`, { method: 'DELETE' });

    await fetch(`${QUEUE_URL}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: 'user.created', payload: { id: user.id, name: user.name } }),
    });

    res.status(201).json({ node: NODE_ID, user });
  } catch (err) {
    console.error(`[web:${NODE_ID}] downstream failure on POST /api/users: ${err.message}`);
    res.status(502).json({ error: 'A downstream service is unavailable' });
  }
});

app.listen(PORT, () => {
  console.log(`[web:${NODE_ID}] listening on :${PORT}`);
});
