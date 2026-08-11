import { svelte } from '@sveltejs/vite-plugin-svelte'
// `vitest/config` rather than `vite`, so the `test` block below is typed rather than tolerated.
import { defineConfig } from 'vitest/config'

/**
 * Where `vite dev` forwards `/api`. The backend's own default port.
 *
 * Overridable for the same reason `docker-compose.yml` takes `COMPOSE_PROJECT_NAME`: parallel
 * worktrees share a machine, and two of them on one port is a confusing failure rather than a
 * loud one.
 */
export const BACKEND_ORIGIN = process.env.KAYA_BACKEND_ORIGIN ?? 'http://localhost:8000'

const SPA_PORT = Number(process.env.KAYA_SPA_PORT ?? 5173)

// The SPA and the API share an origin in production: one deployable artifact serves both
// (ADR 0001, pandan ADR 0003). The dev server has two processes, so it needs a proxy to keep
// that promise true locally — otherwise every fetch would need an absolute URL in dev and a
// relative one in production, and CORS would exist for no reason.
export default defineConfig({
  plugins: [svelte()],
  // Under vitest, resolve Svelte's *browser* entry points. Without this the client runtime is
  // resolved through the `node` condition — the SSR build — and `mount()` renders nothing into a
  // jsdom document while failing silently rather than loudly. Guarded on `VITEST` so `vite build`
  // keeps its own resolution untouched.
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  server: {
    port: SPA_PORT,
    // Fail rather than drift to 5174. A dev server that silently moves leaves your browser on
    // the old port, showing either nothing or someone else's app.
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    include: ['tests/**/*.test.ts'],
    // `node` stays the default, and a test that wants a DOM asks for one with a
    // `// @vitest-environment jsdom` docblock at the top of its own file (KAN-552).
    //
    // Two reasons for per-file opt-in rather than a global `environment: 'jsdom'`. The existing
    // `tests/dev-proxy.test.ts` imports *this file*, and a config module evaluated inside a fake
    // DOM is a config module whose environment checks can lie. And a jsdom document costs ~100 ms
    // to construct per file, which the pure-function tests have no use for.
    //
    // Not `environmentMatchGlobs`: it is gone in vitest 4. Not a second project either — a
    // `projects` split would put the DOM choice in a file none of the DOM tests are in, which is
    // the same discoverability problem one directory further away.
    environment: 'node',
  },
})
