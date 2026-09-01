/**
 * Shared e2e fixtures: authenticating a page through the real landing-state paste flow, and thin
 * API helpers for setup a test doesn't want to spend UI steps on.
 *
 * `pasteToken` drives `Landing.svelte`'s actual form rather than seeding `sessionStorage` directly
 * (`page.evaluate(() => sessionStorage.setItem(...))` would work and would be faster, but it would
 * also mean this suite never exercises the one flow SLICES.md's landing-state bullet is actually
 * about, and `landing.spec.ts` needs the unauthenticated form regardless — reusing it here is one
 * fewer thing this suite asserts two different ways).
 */
import { type APIRequestContext, type Page, expect, test as base } from '@playwright/test'

import { fakeToken, prefixedTitle } from './env'

export { prefixedTitle }

/** Drive the real paste form with the fake pandan bearer, and wait for the shell to leave landing. */
export async function pasteToken(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByTestId('paste-form').locator('input[type="password"]').fill(fakeToken())
  await page.getByTestId('paste-form').getByRole('button', { name: 'Use this token' }).click()
  await expect(page.locator('.shell')).not.toHaveClass(/unauthenticated/)
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
 * `authedPage`: a page that has already been through the real paste flow.
 *
 * `request` here is Playwright's own built-in fixture — same `baseURL` as `page`'s, scoped to the
 * one test using it. `apiCreateNote`/`apiUpdateNote`/`apiDeleteNote` above are typed against it
 * rather than against `page.request` specifically, so a test can call them with either.
 */
export const test = base.extend<{ authedPage: Page }>({
  authedPage: async ({ page }, use) => {
    await pasteToken(page)
    await use(page)
  },
})

export { expect }
