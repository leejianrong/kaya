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
  },
})
