/**
 * The three things every file under `e2e/` needs and none of them should compute twice: the fake
 * bearer `scripts/test-e2e.sh` told both this suite and `scripts/e2e/fake_pandan.py` to agree on,
 * the base URL of the stack it started, and this run's id (see `global-setup.ts`).
 */

/**
 * Must match `fake_pandan.py`'s `KAYA_E2E_FAKE_PANDAN_TOKEN` exactly — `scripts/test-e2e.sh` sets
 * both from the same shell variable, so there is deliberately no independent default here that
 * could drift from that script's. A missing value fails loudly rather than falling back to a guess
 * a differently-configured fake pandan would reject.
 */
export function fakeToken(): string {
  const token = process.env.KAYA_E2E_FAKE_PANDAN_TOKEN
  if (!token) {
    throw new Error(
      'KAYA_E2E_FAKE_PANDAN_TOKEN is not set. Run this suite through `make test-e2e` / ' +
        'scripts/test-e2e.sh, which sets it for both this process and the fake pandan container.',
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
