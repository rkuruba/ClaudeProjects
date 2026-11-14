// Read replica (Chapter 1: "Database replication" - slave node).
// Serves ALL reads so the primary is freed up to handle writes.
// Polls the primary's WAL and applies entries with a deliberate delay to make
// replication lag visible - a real behavior the book calls out explicitly:
// a write to the primary is not guaranteed to be immediately visible on a replica.
import express from 'express';

const PORT = process.env.PORT || 5001;
const PRIMARY_URL = process.env.PRIMARY_URL || 'http://localhost:5000';
const REPLICATION_LAG_MS = Number(process.env.REPLICATION_LAG_MS || 1200);

const app = express();
let users = [];
let lastAppliedSeq = 0;

app.get('/health', (_req, res) => res.json({ ok: true }));

app.get('/users', (_req, res) => {
  res.json(users);
});

app.get('/status', (_req, res) => {
  res.json({ lastAppliedSeq, replicationLagMs: REPLICATION_LAG_MS });
});

async function pollPrimary() {
  try {
    const res = await fetch(`${PRIMARY_URL}/wal?since=${lastAppliedSeq}`, {
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return;
    const entries = await res.json();

    for (const entry of entries) {
      // Simulate the network + disk-flush delay a real replica has before
      // a WAL entry is applied and visible to readers.
      setTimeout(() => {
        if (entry.type === 'insert') {
          users.push(entry.row);
          console.log(`[db-replica] applied WAL seq=${entry.seq} -> user#${entry.row.id} (lag=${REPLICATION_LAG_MS}ms)`);
        }
      }, REPLICATION_LAG_MS);
      lastAppliedSeq = Math.max(lastAppliedSeq, entry.seq);
    }
  } catch {
    // Primary unreachable this cycle; retry on next poll.
  }
}
setInterval(pollPrimary, 500);

app.listen(PORT, () => {
  console.log(`[db-replica] listening on :${PORT}, tailing ${PRIMARY_URL}`);
});
