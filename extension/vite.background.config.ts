import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

// MV3 service worker (ES module). Runs first: empties dist and copies public/ (manifest, icons).
export default defineConfig({
  root: r('.'),
  publicDir: r('public'),
  resolve: { alias: { '@lnz/shared': r('../shared/src/index.ts') } },
  build: {
    outDir: r('dist'),
    emptyOutDir: true,
    target: 'chrome116',
    minify: true,
    lib: { entry: r('src/background/index.ts'), formats: ['es'], fileName: () => 'background.js' },
  },
});
