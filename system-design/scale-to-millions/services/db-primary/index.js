// Primary database (Chapter 1: "Database replication" - master node).
// Accepts ALL writes. Every write is appended to a write-ahead log (WAL) that
// the replica polls, exactly like Postgres/MySQL streaming replication -
// just implemented over plain HTTP instead of a binary replication protocol.
import express from 'express';

const PORT = process.env.PORT || 5000;
const app = express();
app.use(express.json());

let users = [];
let nextId = 1;
const wal = []; // { seq, type, row, ts }
let seq = 0;

app.get('/health', (_req, res) => res.json({ ok: true }));

app.post('/users', (req, res) => {
  const { name } = req.body;
  if (!name) return res.status(400).json({ error: 'name is required' });

  const row = { id: nextId++, name, createdAt: new Date().toISOString() };
  users.push(row);

  seq++;
  wal.push({ seq, type: 'insert', row, ts: Date.now() });

  console.log(`[db-primary] WRITE user#${row.id} "${row.name}" (wal seq=${seq})`);
  res.status(201).json(row);
});

app.get('/users', (_req, res) => {
  // Primary can also serve reads, but Chapter 1's whole point is that reads
  // should go to replicas instead - the web tier deliberately avoids this route.
  res.json(users);
});

// Polled by the replica to pull new WAL entries since its last applied seq.
app.get('/wal', (req, res) => {
  const since = Number(req.query.since || 0);
  res.json(wal.filter((entry) => entry.seq > since));
});

app.listen(PORT, () => {
  console.log(`[db-primary] listening on :${PORT}`);
});
