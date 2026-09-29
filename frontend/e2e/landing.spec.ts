/**
 * SLICES.md §V3 end-to-end bullet 5, updated for ADR 0012's cutover (KAN-1740) and again for
 * KAN-1791: "An unauthenticated visitor sees the landing state, a working GitHub sign-in button,
 * and a link to mint a kaya token by hand."
 *
 * Before KAN-1740 this asserted a link to pandan, built from `GET /api/v1/meta`'s `pandan_url`
 * (`fake-pandan`, an internal-only test double this suite no longer needs — see
 * `docker-compose.e2e.yml`'s header). Before KAN-1791 it also asserted a paste form — `Landing.svelte`
 * no longer has one at all: GitHub sign-in is the page's one and only credential-acquisition path,
 * and the `identity-note` section is prose plus a link to `/tokens` for minting a *named* bearer by
 * hand, not a place to type one in.
 *
 * No `authedPage` fixture and no `login()` here — this is the one test in the suite that must *not*
 * authenticate, and it never touches a cookie or `sessionStorage`.
 */
import { expect, test } from './fixtures'

test('an unauthenticated visitor sees the landing state with GitHub sign-in and no paste form', async ({
  page,
}) => {
  await page.goto('/')

  await expect(page.locator('.shell')).toHaveClass(/unauthenticated/)
  await expect(page.getByTestId('github-signin')).toBeVisible()
  // KAN-1791: there is no credential-typing surface left on this page at all.
  await expect(page.getByTestId('paste-form')).toHaveCount(0)
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  // The authenticated regions must be absent, not merely hidden — no sidebar, no note list, no
  // credential to have leaked into this tab before a session was ever established.
  await expect(page.locator('.sidebar')).toHaveCount(0)

  // `Landing.svelte`'s identity-note section: a same-origin link to kaya's own Tokens page, for
  // minting a *named* bearer (the CLI, a script, another device) rather than signing in with it.
  // Scoped to that section specifically: the shell's own header also links to `/tokens` (visible
  // even signed out), and this test is about `Landing.svelte`'s own copy, not the header's.
  const identitySection = page.getByRole('region', { name: 'Kaya mints its own credentials' })
  const tokensLink = identitySection.getByRole('link', { name: 'Tokens' })
  await expect(tokensLink).toBeVisible()
  await expect(tokensLink).toHaveAttribute('href', '/tokens')
})
