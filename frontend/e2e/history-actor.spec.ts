/**
 * KAY-138: the History tab says who made each version and diffs two of them.
 *
 * One note, three saves by two channels: a create and an edit through the suite's `kaya_pat_` bearer
 * (a token), then an edit through the page's own cookie session (the web). The same flow runs at
 * desktop, medium (pane below the note) and, in `mobile-history-diff.spec.ts`, in the phone sheet.
 * Set `KAYA_SHOT_DIR` to also write screenshots there (light and dark) for review.
 */
import { apiDeleteNote, expect, test } from './fixtures'
import { seedThreeVersions, shoot } from './history-helpers'

for (const [label, width, height] of [
  ['desktop', 1440, 900],
  ['medium', 720, 900],
] as const) {
  test(`${label}: each version says who made it, and Changes shows a line diff`, async ({
    authedPage: page,
    request,
  }) => {
    const note = await seedThreeVersions(page, request)
    try {
      await page.setViewportSize({ width, height })
      await page.goto(`/notes/${note.ref}`)
      await expect(page.getByTestId('title-input')).toHaveValue(note.title)
      await page.getByTestId('toggle-details').click()
      const pane = page.locator('#supporting-pane')
      await pane.getByRole('tab', { name: 'History' }).click()

      const actors = pane.getByTestId('history-actor')
      await expect(actors).toHaveCount(3)
      await expect(actors.nth(0)).toHaveText('You · web')
      await expect(actors.nth(1)).toHaveText(/^You · Token .+\(kaya_pat_\w+…\)$/)
      await expect(actors.nth(2)).toHaveText(/^You · Token /)

      await pane.getByTestId('history-row').nth(1).click()
      await pane.getByTestId('history-view-changes').click()
      await expect(pane.getByTestId('history-diff-stat')).toContainText('v1 to v2: +2 −1')
      const added = pane.locator('.drow.add')
      await expect(added).toHaveCount(2)
      await expect(added.first()).toContainText('beta changed')
      await expect(pane.locator('.drow.del')).toContainText('beta')

      // Nothing overflows sideways at this width.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow).toBeLessThanOrEqual(0)
      await shoot(page, `history-diff-${label}`)
    } finally {
      await apiDeleteNote(request, note.ref)
    }
  })
}
