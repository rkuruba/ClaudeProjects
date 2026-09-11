// Boots every service that makes up the system, each as its own OS process
// communicating over localhost HTTP - the same shape as separate machines
// talking over a network, just without needing Docker or multiple hosts.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const colors = ['\x1b[36m', '\x1b[35m', '\x1b[33m', '\x1b[32m', '\x1b[34m', '\x1b[91m', '\x1b[92m', '\x1b[94m', '\x1b[95m'];
const reset = '\x1b[0m';

const services = [
  { name: 'cache', script: 'services/cache/index.js', env: { PORT: 4000 } },
  { name: 'db-primary', script: 'services/db-primary/index.js', env: { PORT: 5000 } },
  { name: 'db-replica', script: 'services/db-replica/index.js', env: { PORT: 5001, PRIMARY_URL: 'http://localhost:5000' } },
  { name: 'queue', script: 'services/queue/index.js', env: { PORT: 6060 } },
  { name: 'cdn', script: 'services/cdn/index.js', env: { PORT: 7000 } },
  { name: 'worker', script: 'services/worker/index.js', env: { QUEUE_URL: 'http://localhost:6060' } },
  {
    name: 'web-1',
    script: 'services/web/index.js',
    env: {
      PORT: 3001, NODE_ID: 'web-1',
      CACHE_URL: 'http://localhost:4000', PRIMARY_URL: 'http://localhost:5000',
      REPLICA_URL: 'http://localhost:5001', QUEUE_URL: 'http://localhost:6060', CDN_URL: 'http://localhost:7000',
    },
  },
  {
    name: 'web-2',
    script: 'services/web/index.js',
    env: {
      PORT: 3002, NODE_ID: 'web-2',
      CACHE_URL: 'http://localhost:4000', PRIMARY_URL: 'http://localhost:5000',
      REPLICA_URL: 'http://localhost:5001', QUEUE_URL: 'http://localhost:6060', CDN_URL: 'http://localhost:7000',
    },
  },
  { name: 'load-balancer', script: 'services/load-balancer/index.js', env: { PORT: 3000, BACKENDS: 'http://localhost:3001,http://localhost:3002' } },
];

const children = [];

function prefixLines(name, color, stream, out) {
  let buf = '';
  stream.on('data', (chunk) => {
    buf += chunk.toString();
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (line.trim()) out.write(`${color}[${name}]${reset} ${line}\n`);
    }
  });
}

services.forEach((svc, i) => {
  const color = colors[i % colors.length];
  const child = spawn(process.execPath, [path.join(__dirname, svc.script)], {
    env: { ...process.env, ...Object.fromEntries(Object.entries(svc.env).map(([k, v]) => [k, String(v)])) },
  });
  prefixLines(svc.name, color, child.stdout, process.stdout);
  prefixLines(svc.name, color, child.stderr, process.stderr);
  children.push(child);
});

console.log('\nAll services starting. Once ready, open http://localhost:3000\n');

function shutdown() {
  console.log('\nShutting down all services...');
  for (const child of children) child.kill();
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
