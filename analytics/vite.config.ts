import { defineConfig, type Plugin, type ViteDevServer, type PreviewServer } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import type { IncomingMessage, ServerResponse } from 'node:http';

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

/**
 * Local event relay for the analytics dashboard.
 *   POST /api/events   <- extension background (or a teammate's service) posts AnalyticsEvent JSON
 *   GET  /api/stream   -> dashboard subscribes over Server-Sent Events
 *   GET  /api/history  -> last events as JSON
 * Bound to 127.0.0.1 only and unauthenticated; no CORS headers, so ordinary web pages
 * cannot post JSON to it from the browser.
 */
function relay(): Plugin {
  const clients = new Set<ServerResponse>();
  const history: string[] = [];
  const MAX_BODY = 256 * 1024;

  const handler = (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const url = (req.url ?? '').split('?')[0];
    if (url === '/api/events' && req.method === 'POST') {
      let size = 0;
      const chunks: Buffer[] = [];
      req.on('data', (c: Buffer) => {
        size += c.length;
        if (size > MAX_BODY) {
          res.statusCode = 413;
          res.end();
          req.destroy();
        } else chunks.push(c);
      });
      req.on('end', () => {
        if (res.writableEnded) return;
        try {
          const ev = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          if (!ev || typeof ev.type !== 'string') throw new Error('missing type');
          const line = JSON.stringify(ev);
          history.push(line);
          if (history.length > 500) history.shift();
          for (const c of clients) c.write(`data: ${line}\n\n`);
          res.statusCode = 204;
          res.end();
        } catch {
          res.statusCode = 400;
          res.end('invalid event');
        }
      });
      return;
    }
    if (url === '/api/stream' && req.method === 'GET') {
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
      res.write(': lnz relay\n\n');
      for (const line of history.slice(-200)) res.write(`data: ${line}\n\n`);
      clients.add(res);
      const ping = setInterval(() => res.write(': ping\n\n'), 15_000);
      req.on('close', () => {
        clearInterval(ping);
        clients.delete(res);
      });
      return;
    }
    if (url === '/api/history' && req.method === 'GET') {
      res.setHeader('content-type', 'application/json');
      res.end(`[${history.join(',')}]`);
      return;
    }
    next();
  };

  return {
    name: 'lnz-relay',
    configureServer(server: ViteDevServer) {
      server.middlewares.use(handler);
    },
    configurePreviewServer(server: PreviewServer) {
      server.middlewares.use(handler);
    },
  };
}

export default defineConfig({
  root: r('.'),
  plugins: [react(), relay()],
  resolve: { alias: { '@lnz/shared': r('../shared/src/index.ts') } },
  server: { host: '127.0.0.1', port: 5174, strictPort: true },
  preview: { host: '127.0.0.1', port: 5174, strictPort: true },
  build: { outDir: r('dist'), emptyOutDir: true },
});
