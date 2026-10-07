/**
 * The three things every file under `e2e/` needs and none of them should compute twice: the real
 * `kaya_pat_…` `scripts/test-e2e.sh` seeds straight into the stack's own database before Playwright
 * starts, the base URL of the stack it started, and this run's id (see `global-setup.ts`).
 */

/**
 * A real, live PAT (ADR 0012) — not a stand-in a stubbed pandan used to accept unconditionally.
 * `scripts/test-e2e.sh` mints it through the already-running `app` container's own code (so it is
 * hashed with that same container's `KAYA_AUTH_SECRET`) and hands the raw secret to this process the
 * only way that works for test-only, never-persisted-to-disk infrastructure: an environment
 * variable, once, before any Playwright worker exists. A missing value fails loudly rather than
 * falling back to a guess kaya's own resolver would correctly reject.
 */
export function fakeToken(): string {
  const token = process.env.KAYA_E2E_TOKEN
  if (!token) {
    throw new Error(
      'KAYA_E2E_TOKEN is not set. Run this suite through `make test-e2e` / scripts/test-e2e.sh, ' +
        'which seeds a real kaya_pat_… and exports it under this name.',
    )
  }
  return token
}

/** The origin `playwright.config.ts`'s `baseURL` also reads — kept independent because this module
 * is imported from Node-side setup/teardown scripts that never see Playwright's resolved config. */
export function baseUrl(): string {
  return process.env.KAYA_E2E_BASE_URL ?? 'http://localhost:8099'
}

/** `global-setup.ts`'s run id. Every note this suite creates carries it in the title. */
export function runId(): string {
  const id = process.env.KAYA_E2E_RUN_ID
  if (!id) {
    throw new Error('KAYA_E2E_RUN_ID is not set — did playwright.config.ts run globalSetup?')
  }
  return id
}

/** A note title that identifies which run created it, for `global-teardown.ts`'s sweep. */
export function prefixedTitle(name: string): string {
  return `${runId()} ${name}`
}
