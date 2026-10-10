/**
 * KAY-138 on a phone: the History tab inside the bottom sheet shows who made each version and the
 * Changes diff, without sideways overflow. Runs only in the `mobile` project (390px, touch).
 */
import { apiDeleteNote, expect, test } from './fixtures'
import { seedThreeVersions, shoot } from './history-helpers'

test('the sheet lists authors and diffs two versions at 390px', async ({
  authedPage: page,
  request,
}) => {
  const note = await seedThreeVersions(page, request)
  try {
    await page.goto(`/notes/${note.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(note.title)
    await page.getByTestId('toggle-details').tap()
    const sheet = page.getByRole('dialog', { name: 'Links and history' })
    await sheet.getByRole('tab', { name: 'History' }).tap()

    await expect(sheet.getByTestId('history-actor').nth(0)).toHaveText('You · web')
    await sheet.getByTestId('history-row').nth(1).tap()
    await sheet.getByTestId('history-view-changes').tap()
    await expect(sheet.getByTestId('history-diff-stat')).toContainText('v1 to v2: +2 −1')

    const box = (await sheet.getByTestId('history-diff').boundingBox())!
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
    await shoot(page, 'history-diff-mobile')
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
