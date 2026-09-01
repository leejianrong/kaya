/**
 * One thing: mint a run id and publish it to every worker process as an environment variable.
 *
 * Playwright's own documented pattern for passing a value from `globalSetup` into test files is
 * `process.env` — workers are spawned as child processes of the one this runs in, so a write here is
 * visible to every test. `fixtures.ts`'s `prefixedTitle()` is the only thing that reads it, and it
 * is what makes every note this suite creates self-identifying (PLAN §Testing approach point 4:
 * "the e2e stack booting itself, with self-cleaning prefixed data").
 *
 * Not a file on disk and not a fixture: a file would need a second read site, and a fixture would
 * have to be re-derived per worker — a single env var set once, before any worker exists, is the
 * plainest thing that is still guaranteed stable for the whole run, including
 * `global-teardown.ts`'s sweep.
 */
export default function globalSetup(): void {
  const stamp = Date.now().toString(36)
  const random = Math.random().toString(36).slice(2, 8)
  process.env.KAYA_E2E_RUN_ID = `e2e-${stamp}-${random}`
}
