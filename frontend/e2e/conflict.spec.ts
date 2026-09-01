/**
 * SLICES.md §V3 end-to-end bullet 2: "Editing the same note in two tabs produces the conflict
 * banner on the second save, showing both versions." **[mutate]**
 *
 * Per CLAUDE.md's mutation-testing convention, this guard was proven for real, not just asserted to
 * exist: `backend/app/api/concurrency.py`'s `enforce_precondition` had its comparison forced to
 * never fire (`if note.updated_at != payload.if_updated_at:` → `if False:`), this test was run
 * against that build, and it failed exactly where the mutation predicts — the second `PATCH`
 * returned `200` instead of `409`, so no `[data-testid="conflict"]` ever appeared and the test's own
 * `await expect(conflict).toBeVisible()` timed out naming that selector. The mutation was reverted
 * with `git apply -R` on a tree with no other pending changes; see the PR description for the full
 * transcript and the `git status --short` check that confirmed a clean restore.
 *
 * Two tabs means two independent, separately-authenticated pages: real browser tabs opened by hand
 * do not share `sessionStorage` unless one opened the other via `window.open` (the HTML living
 * standard scopes it to a browsing-context group), and `lib/auth.ts` is built on exactly that
 * assumption — a pasted PAT is per-tab. So both `pageA` and `pageB` below run the real paste flow
 * independently, against the *same* fake bearer (this suite's one principal), which is enough:
 * ADR 0009's precondition is keyed on `updated_at`, not on who the two writers are.
 */
import { apiCreateNote, expect, pasteToken, prefixedTitle, test } from './fixtures'

test('two tabs editing one note: the second save shows the conflict banner with both versions', async ({
  context,
  request,
}) => {
  const title = prefixedTitle('conflict')
  const note = await apiCreateNote(request, { title, body: 'Original body.\n' })

  const pageA = await context.newPage()
  const pageB = await context.newPage()

  await pasteToken(pageA)
  await pasteToken(pageB)

  // Both tabs open the note **before either edits it**, so both hold the same original
  // `updated_at` as their save precondition — the property the rest of this test depends on.
  await pageA.goto(`/notes/${note.ref}`)
  await pageB.goto(`/notes/${note.ref}`)
  await expect(pageA.getByTestId('title-input')).toHaveValue(title)
  await expect(pageB.getByTestId('title-input')).toHaveValue(title)

  const editorA = pageA.locator('.editor-host .cm-content')
  await editorA.click()
  await pageA.keyboard.type('Written by tab A.')
  await pageA.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(pageA.getByTestId('save-state')).toHaveText(/^saved · now at /)

  const editorB = pageB.locator('.editor-host .cm-content')
  await editorB.click()
  await pageB.keyboard.type('Written by tab B.')
  await pageB.getByRole('button', { name: 'Save', exact: true }).click()

  const conflict = pageB.getByTestId('conflict')
  await expect(conflict).toBeVisible()
  await expect(pageB.getByTestId('save-error')).toHaveCount(0)

  // Both versions, per the bullet's own wording. `attempted` is what tab B tried to write;
  // `stored` is tab A's save, which is what actually landed.
  await expect(pageB.getByTestId('conflict-mine-body')).toContainText('Written by tab B.')
  await expect(pageB.getByTestId('conflict-theirs-body')).toContainText('Written by tab A.')
  await expect(pageB.getByTestId('conflict-attempted')).toBeVisible()
  await expect(pageB.getByTestId('conflict-stored')).toBeVisible()

  // Tab A's own view is untouched — nothing here should have refused *its* save.
  await expect(pageA.getByTestId('conflict')).toHaveCount(0)
})
