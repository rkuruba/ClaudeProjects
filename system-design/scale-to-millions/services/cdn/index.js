// CDN (Chapter 1: "Content delivery network").
// Serves static assets (CSS/JS/images) from a server dedicated to that job,
// with long-lived cache headers, so the web tier is never bothered with
// requests for files that never change per-request. In production this
// would be a real CDN edge node caching content close to the user;
// here it's simulated as its own local process on its own port.
import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 7000;
const app = express();

app.get('/health', (_req, res) => res.json({ ok: true }));

app.use(
  '/static',
  express.static(path.join(__dirname, '..', '..', 'public-cdn'), {
    setHeaders: (res) => {
      res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
      res.setHeader('x-served-by', 'cdn');
    },
  }),
);

app.listen(PORT, () => {
  console.log(`[cdn] listening on :${PORT}`);
});
