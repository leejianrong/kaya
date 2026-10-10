/**
 * KAY-168 on the phone (390px, touch): rows carry a visible `...` button, the menu fits the screen
 * and moves a note, drag is not enabled (it would fight scrolling), and nothing scrolls sideways.
 */
import { runId } from './env'
import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

test('phone: the row menu moves a note; rows are not draggable; no horizontal scroll', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-mobile-org`
  const note = await apiCreateNote(request, {
    title: prefixedTitle('phone mover'),
    path: `${root}/a/phone.md`,
  })
  const other = await apiCreateNote(request, {
    title: prefixedTitle('phone other'),
    path: `${root}/b/other.md`,
  })
  try {
    await page.goto('/')
    const row = page.locator(`a.row.note[data-id="${note.ref}"]`)
    await expect(row).toBeVisible()
    await expect(row).not.toHaveAttribute('draggable', 'true')

    const more = page.locator(`li:has(> a[data-id="${note.ref}"]) > .more`)
    await expect(more).toBeVisible()
    const box = await more.boundingBox()
    expect(box!.width).toBeGreaterThanOrEqual(44)
    expect(box!.height).toBeGreaterThanOrEqual(44)

    await more.tap()
    const menu = page.getByRole('menu')
    await expect(menu).toBeVisible()
    await menu.getByRole('menuitem', { name: 'Move to…' }).tap()
    const edges = await menu.boundingBox()
    expect(edges!.x).toBeGreaterThanOrEqual(0)
    expect(edges!.x + edges!.width).toBeLessThanOrEqual(390)
    await menu.getByRole('menuitem', { name: `${root}/b`, exact: true }).tap()

    await expect(page.getByTestId('tree-toast')).toContainText('Moved')
    await expect(
      page.locator(`li:has(> button[data-id="${root}/b"]) a[data-id="${note.ref}"]`),
    ).toBeVisible()

    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
  } finally {
    await apiDeleteNote(request, note.ref)
    await apiDeleteNote(request, other.ref)
  }
})
