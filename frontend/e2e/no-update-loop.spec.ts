/**
 * SLICES.md §V3 end-to-end bullet 3: "Typing in the editor does not cause an update loop: a fixed
 * 20-keystroke sequence produces exactly one final document state and exactly one `PATCH` per
 * elapsed debounce interval, asserted as a call count." **[mutate]**
 *
 * **What "per elapsed debounce interval" means against the code that actually shipped, rather than
 * against the bullet's own words** (CLAUDE.md: "trust the code over the docs" — this bullet predates
 * the implementation and the implementation found a different, stronger answer than a debounce
 * timer). `EditorPane.svelte` has no autosave and no debounce at all: a `PATCH` is sent only from
 * the Save button or `Mod-S` (`onSaveKey` → `save()`), and CM6's `onChange` only ever sets local
 * runes (`dirty`, `saved = null`) and republishes the document through the `ondocument` seam — never
 * a request. So "one `PATCH` per elapsed debounce interval" over an interval of *typing with no save
 * triggered* is zero, not one-per-some-timer, and that is the stronger and more specific claim this
 * test makes: **zero** `PATCH`es from the 20 keystrokes themselves, and **exactly one** from the
 * single explicit Save that follows — the update loop PLAN §Open risks warns about would instead
 * show up as a `PATCH` fired by `onChange` itself, or as more than one from an effect re-triggering.
 *
 * Per CLAUDE.md's mutation-testing convention, this guard was proven for real: `onChange` in
 * `EditorPane.svelte`'s `build()` was mutated to call `void save()` on every keystroke — the exact
 * per-keystroke autosave shape this test exists to rule out — and this test was run against that
 * build. It failed on the assertion right after typing (`expect(patchCount).toBe(0)`), reporting 3
 * rather than 0. Not "one per keystroke": `write()`'s own `saving` guard makes each `onChange`-fired
 * save a no-op while a previous one is still in flight, so the count is throttled to roughly one
 * per round trip rather than one per character — and it is exactly this throttling, observed rather
 * than guessed at beforehand, that makes "count is nonzero" the right assertion for this mutation
 * and not "count equals 20". The mutation was reverted with `git apply -R` on an otherwise-clean
 * tree; see the PR description for the full transcript and the `git status --short` check
 * confirming a clean restore.
 */
import { fakeToken } from './env'
import { apiCreateNote, expect, prefixedTitle, test } from './fixtures'

// Exactly 20 characters — counted, not trimmed to length, so the sequence stays legible.
const KEYSTROKES = 'kayaE2eUpdateLoopChk'

test('20 keystrokes cause no PATCH, and one Save causes exactly one', async ({
  authedPage: page,
  request,
}) => {
  expect(KEYSTROKES).toHaveLength(20)

  const title = prefixedTitle('no-update-loop')
  const note = await apiCreateNote(request, { title, body: '' })

  let patchCount = 0
  page.on('request', (req) => {
    if (req.method() === 'PATCH' && req.url().includes(`/api/v1/notes/${note.ref}`)) {
      patchCount += 1
    }
  })

  await page.goto(`/notes/${note.ref}`)
  await expect(page.getByTestId('title-input')).toHaveValue(title)

  const editor = page.locator('.editor-host .cm-content')
  await editor.click()
  await page.keyboard.type(KEYSTROKES)

  await expect(page.getByTestId('save-state')).toHaveText('unsaved changes')
  expect(patchCount, '20 keystrokes must not send any PATCH on their own').toBe(0)

  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-state')).toHaveText(/^saved · now at /)
  expect(patchCount, 'exactly one explicit Save must send exactly one PATCH').toBe(1)

  // "Exactly one final document state" — on screen and on the server, not just in the count above.
  await expect(editor).toHaveText(KEYSTROKES)
  const fetched = await request.get(`/api/v1/notes/${note.ref}`, {
    headers: { Authorization: `Bearer ${fakeToken()}` },
  })
  expect(fetched.ok()).toBeTruthy()
  const stored = (await fetched.json()) as { body: string }
  expect(stored.body).toBe(KEYSTROKES)
})
