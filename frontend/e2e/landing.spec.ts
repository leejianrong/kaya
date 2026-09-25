/**
 * SLICES.md §V3 end-to-end bullet 5, updated for ADR 0012's cutover (KAN-1740): "An unauthenticated
 * visitor sees the landing state and a working link to mint a kaya token."
 *
 * Before the cutover this asserted a link to pandan, built from `GET /api/v1/meta`'s `pandan_url`
 * (`fake-pandan`, an internal-only test double this suite no longer needs — see
 * `docker-compose.e2e.yml`'s header). `Landing.svelte` stopped linking to pandan the same PR that
 * retired that resolver: identity comes from kaya's own `/tokens` page now, not from an operator's
 * pandan deployment, so there is no `pandan_url` for an unauthenticated visitor to need at all.
 *
 * No `authedPage` fixture and no `pasteToken` here — this is the one test in the suite that must
 * *not* authenticate, and it never touches `sessionStorage`.
 */
import { expect, test } from './fixtures'

test('an unauthenticated visitor sees the landing state with a working kaya-token link', async ({
  page,
}) => {
  await page.goto('/')

  await expect(page.locator('.shell')).toHaveClass(/unauthenticated/)
  await expect(page.getByTestId('paste-form')).toBeVisible()
  // The authenticated regions must be absent, not merely hidden — no sidebar, no note list, no
  // credential to have leaked into this tab before a token was ever pasted.
  await expect(page.locator('.sidebar')).toHaveCount(0)
  await expect(page.getByTestId('credential-state')).toHaveText('token not set')

  // `Landing.svelte`'s "Get a kaya token" section: a same-origin link to kaya's own Tokens page,
  // not an external `target="_blank"` link the way the old pandan link was — minting a token is
  // now a kaya-native flow, not a hop to a sibling app. Scoped to that section specifically: the
  // shell's own header also links to `/tokens` (visible even signed out), and this test is about
  // `Landing.svelte`'s own copy, not the header's.
  const identitySection = page.getByRole('region', { name: 'Get a kaya token' })
  const tokensLink = identitySection.getByRole('link', { name: 'Tokens' })
  await expect(tokensLink).toBeVisible()
  await expect(tokensLink).toHaveAttribute('href', '/tokens')
})
