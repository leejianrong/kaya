/**
 * SLICES.md §V3 end-to-end bullet 4: "The folder tree reflects a `path` change made through the
 * API without a reload of the whole app."
 *
 * "Made through the API" is `EditorPane.svelte`'s `savePath()` — KAN-1043's editable path field,
 * which is a `PATCH /api/v1/notes/{ref}` exactly like every other write in this SPA (`lib/notes.ts`:
 * `moveNote` is documented sugar over the identical call, and the field wires directly to
 * `updateNote`, ADR 0008). "Without a reload of the whole app" is checked two ways: the sidebar's
 * tree updates from `App.svelte`'s `onupdated` seam with no `page.reload()` or navigation anywhere
 * in this test, and a marker written onto `window` before the edit is still there afterwards — a
 * real reload would have thrown it away.
 */
import { runId } from './env'
import { apiCreateNote, expect, prefixedTitle, test } from './fixtures'

test('the sidebar tree follows a path change without reloading the page', async ({
  authedPage: page,
  request,
}) => {
  const before = `${runId()}-before`
  const after = `${runId()}-after`
  const title = prefixedTitle('folder-tree note')

  await apiCreateNote(request, { title, path: `${before}/note.md` })

  // A fresh landing → paste → home reaches the note list *after* the note above exists, so the
  // first tree render already contains it — nothing here waits on a second fetch.
  await page.goto('/')

  const tree = page.getByTestId('note-tree')
  await expect(tree).toContainText('before')
  await expect(tree.locator('a.row.note', { hasText: title })).toBeVisible()

  await page.evaluate(() => {
    // A real reload replaces `window` entirely; client-side routing does not touch it at all. This
    // is what makes "no reload happened" checkable rather than merely unobserved.
    ;(window as unknown as Record<string, boolean>).__e2eNoReload = true
  })

  await tree.locator('a.row.note', { hasText: title }).click()
  await expect(page.getByTestId('title-input')).toHaveValue(title)

  const pathInput = page.getByTestId('path-input')
  await expect(pathInput).toHaveValue(`${before}/note.md`)
  await pathInput.fill(`${after}/note.md`)
  await pathInput.blur()

  await expect(page.getByTestId('path-error')).toHaveCount(0)
  await expect(tree).toContainText('after')
  await expect(tree.locator('a.row.note', { hasText: title })).toBeVisible()
  await expect(tree).not.toContainText(before)

  const marker = await page.evaluate(
    () => (window as unknown as Record<string, boolean>).__e2eNoReload,
  )
  expect(marker).toBe(true)
})
