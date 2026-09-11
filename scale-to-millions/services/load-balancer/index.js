// Load balancer (Chapter 1: "Load balancer").
// Distributes incoming traffic round-robin across N stateless web servers,
// and stops routing to any server that fails its health check.
import http from 'node:http';

const PORT = process.env.PORT || 3000;
const BACKENDS = (process.env.BACKENDS || 'http://localhost:3001,http://localhost:3002')
  .split(',')
  .map((url) => ({ url, healthy: true }));

let nextIndex = 0;

function pickBackend() {
  const healthy = BACKENDS.filter((b) => b.healthy);
  if (healthy.length === 0) return null;
  const backend = healthy[nextIndex % healthy.length];
  nextIndex++;
  return backend;
}

async function checkHealth() {
  for (const backend of BACKENDS) {
    try {
      const res = await fetch(`${backend.url}/health`, { signal: AbortSignal.timeout(1500) });
      backend.healthy = res.ok;
    } catch {
      backend.healthy = false;
    }
  }
}
setInterval(checkHealth, 5000);
checkHealth();

const server = http.createServer((clientReq, clientRes) => {
  const backend = pickBackend();
  if (!backend) {
    clientRes.writeHead(503, { 'Content-Type': 'application/json' });
    clientRes.end(JSON.stringify({ error: 'No healthy backends available' }));
    return;
  }

  const target = new URL(clientReq.url, backend.url);
  const proxyReq = http.request(
    target,
    { method: clientReq.method, headers: clientReq.headers },
    (proxyRes) => {
      clientRes.writeHead(proxyRes.statusCode, {
        ...proxyRes.headers,
        'x-load-balancer': 'round-robin',
      });
      proxyRes.pipe(clientRes);
    },
  );

  proxyReq.on('error', () => {
    backend.healthy = false;
    clientRes.writeHead(502, { 'Content-Type': 'application/json' });
    clientRes.end(JSON.stringify({ error: `Backend ${backend.url} unreachable` }));
  });

  clientReq.pipe(proxyReq);
});

server.listen(PORT, () => {
  console.log(`[load-balancer] listening on :${PORT}, backends: ${BACKENDS.map((b) => b.url).join(', ')}`);
});
