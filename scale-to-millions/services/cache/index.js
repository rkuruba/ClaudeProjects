// Cache tier (Chapter 1: "Cache").
// Stands in for Redis/Memcached: a fast in-memory key-value store, separate
// from the web tier, so multiple stateless web servers share one cache
// instead of each holding its own (which would cause inconsistent results
// depending on which server handled a request).
import express from 'express';

const PORT = process.env.PORT || 4000;
const app = express();
app.use(express.json());

const store = new Map(); // key -> { value, expiresAt }
let hits = 0;
let misses = 0;

app.get('/health', (_req, res) => res.json({ ok: true }));

app.get('/stats', (_req, res) => res.json({ hits, misses, keys: store.size }));

app.get('/cache/:key', (req, res) => {
  const entry = store.get(req.params.key);
  if (!entry || entry.expiresAt < Date.now()) {
    store.delete(req.params.key);
    misses++;
    return res.status(404).json({ hit: false });
  }
  hits++;
  res.json({ hit: true, value: entry.value });
});

app.put('/cache/:key', (req, res) => {
  const { value, ttlMs = 10000 } = req.body;
  store.set(req.params.key, { value, expiresAt: Date.now() + ttlMs });
  res.json({ ok: true });
});

app.delete('/cache/:key', (req, res) => {
  store.delete(req.params.key);
  res.json({ ok: true });
});

app.listen(PORT, () => {
  console.log(`[cache] listening on :${PORT}`);
});
