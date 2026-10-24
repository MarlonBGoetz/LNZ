import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

// Content script: must be a single classic (IIFE) file. CSS is inlined into the Shadow DOM.
export default defineConfig({
  root: r('.'),
  publicDir: false,
  plugins: [react()],
  resolve: { alias: { '@lnz/shared': r('../shared/src/index.ts') } },
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: r('dist'),
    emptyOutDir: false,
    target: 'chrome116',
    minify: true,
    cssCodeSplit: false,
    lib: { entry: r('src/content/index.tsx'), formats: ['iife'], name: 'LNZContent', fileName: () => 'content.js' },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
