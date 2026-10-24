import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  resolve: {
    alias: { '@lnz/shared': fileURLToPath(new URL('./shared/src/index.ts', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['shared/test/**/*.test.ts', 'extension/test/**/*.test.ts'],
  },
});
