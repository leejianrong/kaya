import { defineConfig, devices } from '@playwright/test'

/**
 * `make test-e2e` (KAN-1070). Chromium only for a first landing — SLICES.md's V3 end-to-end bullets
 * ask for a real browser against a real stack, not a cross-browser matrix, and CLAUDE.md's brief for
 * this card is explicit about not gold-plating.
 *
 * The stack this points at is booted and torn down by `scripts/test-e2e.sh`, never by this file:
 * `KAYA_E2E_BASE_URL` names it, and there is no `webServer` block here, because the server in
 * question is a whole docker-compose stack (db, migration, app, fake pandan) and not a single
 * process this config could `npm run` on its own.
 */
const baseURL = process.env.KAYA_E2E_BASE_URL ?? 'http://localhost:8099'

export default defineConfig({
  testDir: './e2e',
  // One shared backend and one shared set of prefixed notes per run (see `fixtures.ts`), so tests
  // run serially rather than fully parallel — nothing here is slow enough that serial execution
  // costs more than the flakiness a second worker racing the same note would cost instead.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [['list']],
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
})
