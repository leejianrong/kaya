/**
 * KAN-1827: backlinks and history as an on-demand pane at desktop width (the `chromium` project).
 * The phone half is `mobile-links-sheet.spec.ts`.
 *
 * Closed by default so the document keeps the width; the Links button opens it (aria-expanded,
 * aria-controls), and the choice survives a reload.
 */
import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

test('expanded: the pane is closed by default, toggles from the top bar and is remembered', async ({
  authedPage: page,
  request,
}) => {
  const target = await apiCreateNote(request, {
    title: prefixedTitle('pane-target'),
    body: 'The note with a backlink.\n',
  })
  const source = await apiCreateNote(request, {
    title: prefixedTitle('pane-source'),
    body: `Mentions [[${target.title}]] here.\n`,
  })
  try {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(`/notes/${target.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(target.title)
    const links = page.getByTestId('toggle-details')
    const pane = page.locator('#supporting-pane')

    // Closed: no pane, and the document has the width.
    await expect(links).toHaveAttribute('aria-expanded', 'false')
    await expect(links).toHaveAttribute('aria-controls', 'supporting-pane')
    await expect(pane).toHaveCount(0)
    const closedWidth = (await page.locator('main').boundingBox())!.width

    await links.click()
    await expect(pane).toBeVisible()
    await expect(links).toHaveAttribute('aria-expanded', 'true')
    await expect(pane.getByRole('tab', { name: 'Backlinks' })).toHaveAttribute('aria-selected', 'true')
    await expect(pane.getByRole('link', { name: new RegExp(source.title) })).toBeVisible()
    const openWidth = (await page.locator('main').boundingBox())!.width
    expect(openWidth).toBeLessThan(closedWidth)
    // It sits beside the document, not over it, and is not a modal.
    const paneBox = (await pane.boundingBox())!
    const mainBox = (await page.locator('main').boundingBox())!
    expect(paneBox.x).toBeGreaterThanOrEqual(mainBox.x + mainBox.width - 1)
    await expect(page.getByRole('dialog')).toHaveCount(0)

    // History tab by keyboard.
    await pane.getByRole('tab', { name: 'Backlinks' }).focus()
    await page.keyboard.press('ArrowRight')
    await expect(pane.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true')

    // Remembered across a reload, and across a navigation to another note.
    await page.reload()
    await expect(page.getByTestId('title-input')).toHaveValue(target.title)
    await expect(pane).toBeVisible()
    await pane.getByRole('tab', { name: 'Backlinks' }).click()
    await pane.getByRole('link', { name: new RegExp(source.title) }).click()
    await expect(page).toHaveURL(new RegExp(`/notes/${source.ref}$`))
    await expect(pane).toBeVisible()

    // Closing is remembered too.
    await links.click()
    await expect(pane).toHaveCount(0)
    await page.reload()
    await expect(page.getByTestId('title-input')).toHaveValue(source.title)
    await expect(pane).toHaveCount(0)
    await expect(links).toHaveAttribute('aria-expanded', 'false')
  } finally {
    await apiDeleteNote(request, source.ref)
    await apiDeleteNote(request, target.ref)
  }
})

test('medium: the pane is closed by default too, and opens below the note', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, { title: prefixedTitle('pane-medium'), body: 'x\n' })
  try {
    await page.setViewportSize({ width: 700, height: 900 })
    await page.goto(`/notes/${note.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(note.title)
    const pane = page.locator('#supporting-pane')
    await expect(pane).toHaveCount(0)
    await page.getByTestId('toggle-details').click()
    await expect(pane).toBeVisible()
    const paneBox = (await pane.boundingBox())!
    const mainBox = (await page.locator('main').boundingBox())!
    expect(paneBox.y).toBeGreaterThanOrEqual(mainBox.y + mainBox.height - 1)
    // Medium and expanded remember separately.
    await page.setViewportSize({ width: 1440, height: 900 })
    await expect(pane).toHaveCount(0)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
