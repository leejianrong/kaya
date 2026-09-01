/**
 * SLICES.md §V3 end-to-end bullet 1: "Create, edit and reload a note in a browser; the text
 * persists."
 *
 * Drives the real UI throughout — the sidebar's "+ New note" prompt, CM6's own contenteditable via
 * real keyboard events (not `.fill()`, which dispatches a bare `input` event CM6 was never asked to
 * understand — see `EditorPane.svelte`'s own docstring on why nothing but a transaction or real
 * typing may touch its document), and the Save button — then forces an actual document reload
 * (`page.reload()`, a fresh HTTP request and a fresh mount) and reads the persisted state back off
 * the server rather than off anything the SPA cached client-side.
 */
import { expect, prefixedTitle, test } from './fixtures'

test('creating, editing and reloading a note persists the edit', async ({ authedPage: page }) => {
  const title = prefixedTitle('persist')
  const body = `Persisted body ${Date.now()}.`

  await page.getByTestId('new-note-button').click()
  await page.getByTestId('create-title-input').fill(title)
  await page.getByTestId('create-confirm').click()

  await expect(page.getByTestId('title-input')).toHaveValue(title)

  const editor = page.locator('.editor-host .cm-content')
  await editor.click()
  await page.keyboard.type(body)

  await expect(page.getByTestId('save-state')).toHaveText('unsaved changes')

  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-state')).toHaveText(/^saved · now at /)

  // A fresh document load — the SPA's own client-side state is gone, and everything on screen after
  // this comes from a re-fetch of the note the reload's own routing lands on (KAN-552's `router.ts`:
  // the URL names the note, and `backend/app/spa.py` serves the app for it).
  await page.reload()

  await expect(page.getByTestId('title-input')).toHaveValue(title)
  await expect(page.locator('.editor-host .cm-content')).toHaveText(body)
})
