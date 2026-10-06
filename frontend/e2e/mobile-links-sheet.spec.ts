/**
 * KAN-1827: backlinks and history as a bottom sheet on a phone. Runs only in the `mobile` project
 * (iPhone 13 profile, 390px wide, touch).
 *
 * What this proves in a real engine: the Links button opens a modal dialog with Backlinks and
 * History tabs; focus goes in and comes back; Escape, the scrim and the close button close it; the
 * arrow keys move between tabs; tapping a backlink navigates and closes the sheet; the sheet leaves
 * the note visible above it. What it cannot prove is a real soft keyboard or a real iOS safe area.
 */
import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

test('the Links button opens a sheet with two tabs, and every way out returns focus to it', async ({
  authedPage: page,
  request,
}) => {
  const target = await apiCreateNote(request, {
    title: prefixedTitle('sheet-target'),
    body: 'The note with a backlink.\n',
  })
  const source = await apiCreateNote(request, {
    title: prefixedTitle('sheet-source'),
    body: `Mentions [[${target.title}]] here.\n`,
  })
  try {
    await page.goto(`/notes/${target.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(target.title)
    const links = page.getByTestId('toggle-details')
    await expect(links).toHaveText('Links')
    await expect(links).toHaveAttribute('aria-expanded', 'false')
    await expect(page.getByRole('dialog')).toHaveCount(0)

    await links.tap()
    const sheet = page.getByRole('dialog', { name: 'Links and history' })
    await expect(sheet).toBeVisible()
    await expect(sheet).toHaveAttribute('aria-modal', 'true')
    await expect(links).toHaveAttribute('aria-expanded', 'true')
    // Focus is on the selected tab, inside the sheet; the page behind does not scroll.
    await expect(sheet.getByRole('tab', { name: 'Backlinks' })).toBeFocused()
    expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden')

    // The note stays visible above the sheet, and the sheet sits on the bottom edge.
    const viewport = page.viewportSize()!
    // The slide-in takes a moment: wait for it to land before measuring.
    await expect
      .poll(async () => Math.round((await sheet.boundingBox())!.y + (await sheet.boundingBox())!.height))
      .toBe(viewport.height)
    const box = (await sheet.boundingBox())!
    expect(box.y).toBeGreaterThanOrEqual(viewport.height * 0.25)
    expect(Math.round(box.y + box.height)).toBe(viewport.height)
    expect(box.width).toBe(viewport.width)

    // Tabs: the arrow keys move and select; the panel follows the selection.
    await page.keyboard.press('ArrowRight')
    await expect(sheet.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true')
    await expect(sheet.getByRole('tab', { name: 'History' })).toBeFocused()
    await expect(sheet.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', /tab-history$/)
    await page.keyboard.press('ArrowLeft')
    await expect(sheet.getByRole('tab', { name: 'Backlinks' })).toHaveAttribute('aria-selected', 'true')

    // Escape closes and focus returns to the opener.
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(links).toBeFocused()
    expect(await page.evaluate(() => document.body.style.overflow)).toBe('')

    // The scrim closes it, tapped above the sheet.
    await links.tap()
    await expect(sheet).toBeVisible()
    await page.mouse.click(viewport.width / 2, 100)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(links).toBeFocused()

    // The close button closes it.
    await links.tap()
    await sheet.getByRole('button', { name: 'Close' }).tap()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(links).toBeFocused()

    // Tab stays inside: from the last control it wraps to the first.
    await links.tap()
    await expect(sheet).toBeVisible()
    await expect(sheet.getByRole('link', { name: new RegExp(source.title) })).toBeVisible()
    await expect(sheet.getByRole('tab', { name: 'Backlinks' })).toBeFocused()
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press('Tab')
      const where = await page.evaluate(
        () => `${document.activeElement?.outerHTML.slice(0, 120)} inDialog=${document.activeElement?.closest('[role="dialog"]') != null}`,
      )
      expect(where, `after Tab ${i + 1}`).toContain('inDialog=true')
    }
    await page.keyboard.press('Escape')

    // Tapping a backlink goes to that note and the sheet is gone.
    await links.tap()
    await sheet.getByRole('link', { name: new RegExp(source.title) }).tap()
    await expect(page).toHaveURL(new RegExp(`/notes/${source.ref}$`))
    await expect(page.getByTestId('title-input')).toHaveValue(source.title)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  } finally {
    await apiDeleteNote(request, source.ref)
    await apiDeleteNote(request, target.ref)
  }
})

test('the sheet lifts above the keyboard and clears the safe area', async ({
  authedPage: page,
  request,
}) => {
  await page.addInitScript(() => {
    const target = new EventTarget()
    const fake = Object.assign(target, {
      height: window.innerHeight,
      offsetTop: 0,
      offsetLeft: 0,
      width: window.innerWidth,
      scale: 1,
    })
    Object.defineProperty(window, 'visualViewport', { value: fake, configurable: true })
    ;(window as unknown as Record<string, unknown>).__keyboard = (px: number) => {
      fake.height = window.innerHeight - px
      target.dispatchEvent(new Event('resize'))
    }
  })
  const note = await apiCreateNote(request, { title: prefixedTitle('sheet-keyboard'), body: 'x\n' })
  try {
    await page.goto(`/notes/${note.ref}`)
    await page.getByTestId('toggle-details').tap()
    const sheet = page.getByRole('dialog')
    await expect(sheet).toBeVisible()
    const viewport = page.viewportSize()!
    await page.evaluate(() => (window as unknown as { __keyboard(px: number): void }).__keyboard(300))
    await expect
      .poll(async () => {
        const b = (await sheet.boundingBox())!
        return Math.round(b.y + b.height)
      })
      .toBe(viewport.height - 300)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('Tab stays inside the sheet while the backlinks are still loading', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, { title: prefixedTitle('sheet-loading'), body: 'x\n' })
  try {
    // Hold the backlinks answer back so Refresh is disabled and the sheet has only three stops.
    await page.route('**/backlinks', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      await route.continue()
    })
    await page.goto(`/notes/${note.ref}`)
    await page.getByTestId('toggle-details').tap()
    const sheet = page.getByRole('dialog')
    await expect(sheet.getByRole('tab', { name: 'Backlinks' })).toBeFocused()
    await expect(sheet.getByRole('button', { name: 'Refresh' })).toBeDisabled()
    for (let i = 0; i < 4; i += 1) {
      await page.keyboard.press('Tab')
      const inside = await page.evaluate(() => document.activeElement?.closest('[role="dialog"]') != null)
      expect(inside, `after Tab ${i + 1}`).toBe(true)
    }
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
