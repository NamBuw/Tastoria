#!/usr/bin/env node
// Serves the web export (dist/) and proxies /api, /healthz, /readyz to the backend on the same origin,
// the way nginx does in deployment (spec v2 §10), so the app can use the relative base URL /api/v1.
//   API_TARGET=http://127.0.0.1:8000 PORT=8080 node scripts/serve-web.mjs
import { createReadStream, existsSync, statSync } from 'node:fs';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { extname, join, normalize, resolve } from 'node:path';

const root = resolve(process.env.DIST ?? 'dist');
const landing = fileURLToPath(new URL('../../landing/', import.meta.url));
const port = Number(process.env.PORT ?? 8080);
const host = process.env.HOST ?? '127.0.0.1';
const target = new URL(process.env.API_TARGET ?? 'http://127.0.0.1:8000');
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.ttf': 'font/ttf',
  '.woff2': 'font/woff2',
  '.map': 'application/json',
};

function proxy(req, res) {
  const up = http.request(
    { hostname: target.hostname, port: target.port, path: req.url, method: req.method, headers: { ...req.headers, host: target.host } },
    (r) => {
      res.writeHead(r.statusCode ?? 502, r.headers);
      r.pipe(res);
    },
  );
  up.on('error', () => {
    res.writeHead(502, { 'content-type': 'application/problem+json' });
    res.end(JSON.stringify({ type: 'about:blank', title: 'API không phản hồi', status: 502, code: 'service_unavailable' }));
  });
  req.pipe(up);
}

http
  .createServer((req, res) => {
    const path = decodeURIComponent((req.url ?? '/').split('?')[0]);
    if (path.startsWith('/api/') || path === '/healthz' || path === '/readyz') return proxy(req, res);
    if (path === '/gioi-thieu') {
      res.writeHead(301, { location: '/gioi-thieu/' });
      return res.end();
    }
    const publicPage = path === '/' || path === '/gioi-thieu/';
    const publicAsset = /^\/gioi-thieu\/(?:style\.css|story\.js|(?:fonts|img)\/[A-Za-z0-9._-]+)$/.test(path);
    if (publicPage || publicAsset) {
      const publicFile = publicPage ? join(landing, 'index.html') : join(landing, path.slice('/gioi-thieu/'.length));
      if (!existsSync(publicFile) || !statSync(publicFile).isFile()) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'content-type': TYPES[extname(publicFile)] ?? 'application/octet-stream', 'cache-control': 'no-cache' });
      return createReadStream(publicFile).pipe(res);
    }
    if (path.startsWith('/gioi-thieu/')) { res.writeHead(404); return res.end(); }
    let file = normalize(join(root, path));
    if (!file.startsWith(root)) {
      res.writeHead(400);
      return res.end();
    }
    if (!existsSync(file) || statSync(file).isDirectory()) file = join(root, 'index.html'); // SPA fallback (web.output single)
    res.writeHead(200, {
      'content-type': TYPES[extname(file)] ?? 'application/octet-stream',
      'cache-control': file.endsWith('index.html') ? 'no-cache' : 'public, max-age=31536000, immutable',
    });
    createReadStream(file).pipe(res);
  })
  .listen(port, host, () => console.log(`Tastoria web: http://${host}:${port} → API ${target.origin}`));
