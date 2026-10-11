// Message queue (Chapter 1: "Message queue").
// Decouples slow/non-critical work (e.g. sending a welcome email) from the
// request path. The web tier publishes a job and responds to the user
// immediately; a separate worker process consumes and processes it later.
import express from 'express';

const PORT = process.env.PORT || 6060; // note: 6000 is on the Fetch spec's "bad ports" blocklist (X11)
const app = express();
app.use(express.json());

const queues = new Map(); // topic -> array of jobs

app.get('/health', (_req, res) => res.json({ ok: true }));

app.post('/publish', (req, res) => {
  const { topic, payload } = req.body;
  if (!topic) return res.status(400).json({ error: 'topic is required' });

  if (!queues.has(topic)) queues.set(topic, []);
  queues.get(topic).push({ payload, publishedAt: Date.now() });

  console.log(`[queue] published to "${topic}": ${JSON.stringify(payload)}`);
  res.status(202).json({ ok: true, queueDepth: queues.get(topic).length });
});

app.get('/consume', (req, res) => {
  const { topic } = req.query;
  const jobs = queues.get(topic);
  if (!jobs || jobs.length === 0) return res.status(204).end();

  const job = jobs.shift();
  res.json(job);
});

app.listen(PORT, () => {
  console.log(`[queue] listening on :${PORT}`);
});
