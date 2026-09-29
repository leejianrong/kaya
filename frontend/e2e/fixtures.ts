/**
 * Shared e2e fixtures: authenticating a page, and thin API helpers for setup a test doesn't want to
 * spend UI steps on.
 *
 * KAN-1791 removed `Landing.svelte`'s paste form entirely — GitHub OAuth is kaya's only login path,
 * and there is no scripted way through a real consent screen in CI. `login()` mints a real
 * `kayaauth` cookie session directly instead, through kaya's own e2e-only `POST /auth/test-login`
 * (gated on `KAYA_E2E_AUTH_BYPASS`, see `Settings.kaya_e2e_auth_bypass`'s own docstring and
 * `docker-compose.e2e.yml`'s `app.environment`, the only place that sets it) — the kaya mirror of
 * pandan's own shipped `E2E_AUTH_BYPASS`/`login()` helper (`pandan/frontend/e2e/helpers.ts`), which
 * hit the identical problem for the identical reason.
 */
import { type APIRequestContext, type Page, expect, test as base } from '@playwright/test'

import { fakeToken, prefixedTitle } from './env'

export { prefixedTitle }

/**
 * The email every fixture in this suite authenticates as by default — the same one
 * `scripts/test-e2e.sh` seeds the suite's `kaya_pat_…` bearer for, so a cookie session from
 * `login()` and a bearer from `fakeToken()` resolve to the **same** `KayaAccount`: notes created
 * through one are visible through the other, exactly as they were when both were the one fake PAT.
 *
 * Not a `.test`/`.invalid`/`.localhost` domain: `POST /auth/test-login` validates this through
 * fastapi-users' `UserCreate` schema, whose `EmailStr` rejects an RFC 2606 reserved-for-testing
 * domain as a "special-use or reserved name" — found by actually running this suite, not reasoned
 * about, since `scripts/test-e2e.sh`'s own direct-DB seed bypasses that validation and would not
 * have caught the mismatch on its own. `example.com` matches pandan's own e2e seam.
 */
const E2E_EMAIL = 'e2e@example.com'

/**
 * Mint a real cookie session for `email`, with no navigation and no GitHub round trip.
 *
 * `page.request` shares this page's own browser-context cookie jar, so the `Set-Cookie` on the
 * response lands where a subsequent `page.goto()` will actually send it — `maxRedirects: 0` keeps
 * the route's own `302` to `/` (`RedirectingCookieTransport`, `app/identity/backend.py`) from being
 * auto-followed, matching pandan's own `login()` for the identical reason: the interesting response
 * is the one carrying the cookie, not whatever the redirect's target answers with.
 */
export async function login(page: Page, email = E2E_EMAIL): Promise<void> {
  const response = await page.request.post('/auth/test-login', {
    data: { email },
    maxRedirects: 0,
  })
  if (response.status() >= 400) {
    throw new Error(`test-login failed (${response.status()}): ${await response.text()}`)
  }
}

interface Note {
  ref: string
  id: number
  title: string
  body: string
  path: string
  created_at: string
  updated_at: string
}

/** `notePath`'s sibling for this file — one percent-encoded segment, same as `lib/notes.ts`. */
function notePath(ref: string): string {
  return `notes/${encodeURIComponent(ref)}`
}

/**
 * Create a note through the API directly, for tests whose subject is not note *creation* — the
 * conflict banner and the folder-tree bullets both need a note to already exist before the part
 * they are actually testing starts.
 */
export async function apiCreateNote(
  api: APIRequestContext,
  input: { title: string; body?: string; path?: string },
): Promise<Note> {
  const response = await api.post('/api/v1/notes', {
    headers: { Authorization: `Bearer ${fakeToken()}` },
    data: input,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Note
}

export async function apiUpdateNote(
  api: APIRequestContext,
  ref: string,
  patch: Record<string, unknown>,
): Promise<Note> {
  const response = await api.patch(notePath(ref), {
    headers: { Authorization: `Bearer ${fakeToken()}` },
    data: patch,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Note
}

export async function apiDeleteNote(api: APIRequestContext, ref: string): Promise<void> {
  const response = await api.delete(notePath(ref), {
    headers: { Authorization: `Bearer ${fakeToken()}` },
  })
  expect(response.ok() || response.status() === 404, await response.text()).toBeTruthy()
}

/**
 * `authedPage`: a page that already has a real cookie session and has landed on the note list.
 *
 * `request` here is Playwright's own built-in fixture — same `baseURL` as `page`'s, scoped to the
 * one test using it. `apiCreateNote`/`apiUpdateNote`/`apiDeleteNote` above are typed against it
 * rather than against `page.request` specifically, so a test can call them with either.
 */
export const test = base.extend<{ authedPage: Page }>({
  authedPage: async ({ page }, use) => {
    await login(page)
    await page.goto('/')
    await expect(page.locator('.shell')).not.toHaveClass(/unauthenticated/)
    await use(page)
  },
})

export { expect }
