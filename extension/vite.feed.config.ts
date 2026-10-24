import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

// Feed filtering scripts. Two classic (IIFE) bundles, no React:
//   vite build -c extension/vite.feed.config.ts --mode main    -> dist/feed-main.js   (MAIN world)
//   vite build -c extension/vite.feed.config.ts --mode bridge  -> dist/feed-bridge.js (isolated world)
export default defineConfig(({ mode }) => {
  const main = mode === 'main';
  return {
    root: r('.'),
    publicDir: false,
    resolve: { alias: { '@lnz/shared': r('../shared/src/index.ts') } },
    build: {
      outDir: r('dist'),
      emptyOutDir: false,
      target: 'chrome116',
      minify: true,
      lib: {
        entry: r(main ? 'src/feed/main-world.ts' : 'src/feed/bridge.ts'),
        formats: ['iife'],
        name: main ? 'LNZFeedMain' : 'LNZFeedBridge',
        fileName: () => (main ? 'feed-main.js' : 'feed-bridge.js'),
      },
      rollupOptions: { output: { inlineDynamicImports: true } },
    },
  };
});
