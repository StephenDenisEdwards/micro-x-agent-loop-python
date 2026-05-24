import { defineConfig, type UserConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// vitest bundles its own vite types which can drift from the workspace's
// vite — cast the plugin to break the version-mismatch chain.
const plugins: UserConfig['plugins'] = [react() as unknown as UserConfig['plugins']] as UserConfig['plugins'];

export default defineConfig({
  plugins,
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/main.tsx',
        'src/vite-env.d.ts',
      ],
    },
  },
});
