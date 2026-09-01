/**
 * SLICES.md §V3 end-to-end bullet 5: "An unauthenticated visitor sees the landing state and a
 * working link to pandan."
 *
 * No `authedPage` fixture and no `pasteToken` here — this is the one test in the suite that must
 * *not* authenticate, and it never touches `sessionStorage`.
 *
 * "A working link" is checked as `Landing.svelte`'s own contract: an `<a>` whose `href` is exactly
 * what `GET /api/v1/meta` reported for `KAYA_PANDAN_URL` (this stack's `docker-compose.e2e.yml`
 * overlay points it at `fake-pandan`, an internal-only test double with no browsable page of its
 * own — see that overlay's header — so this asserts the link kaya's own mechanism produces from
 * `/api/v1/meta`, not that the destination happens to render a page in this environment), opened in
 * a new tab (`target="_blank"`) with `rel="noopener noreferrer"`.
 */
import { expect, test } from './fixtures'

test('an unauthenticated visitor sees the landing state with a working pandan link', async ({
  page,
  request,
}) => {
  const meta = await request.get('/api/v1/meta')
  expect(meta.ok()).toBeTruthy()
  const { pandan_url: pandanUrl } = (await meta.json()) as { pandan_url: string }
  // `lib/meta.ts`'s `pandanHref` renders `new URL(origin).href`, not the operator's string
  // verbatim — the URL constructor normalises `http://fake-pandan:8000` to
  // `http://fake-pandan:8000/`, so the expected href has to go through the same normalisation.
  const expectedHref = new URL(pandanUrl).href

  await page.goto('/')

  await expect(page.locator('.shell')).toHaveClass(/unauthenticated/)
  await expect(page.getByTestId('paste-form')).toBeVisible()
  // The authenticated regions must be absent, not merely hidden — no sidebar, no note list, no
  // credential to have leaked into this tab before a token was ever pasted.
  await expect(page.locator('.sidebar')).toHaveCount(0)
  await expect(page.getByTestId('credential-state')).toHaveText('token not set')

  const pandanLink = page.locator(`a[href="${expectedHref}"]`).first()
  await expect(pandanLink).toBeVisible()
  await expect(pandanLink).toHaveAttribute('target', '_blank')
  await expect(pandanLink).toHaveAttribute('rel', /noopener/)
  await expect(pandanLink).toHaveAttribute('rel', /noreferrer/)
})
