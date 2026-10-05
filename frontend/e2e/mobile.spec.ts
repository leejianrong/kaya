/**
 * KAN-1818: the phone. Runs only in the `mobile` project (iPhone 13 profile, 390px wide).
 *
 * Before this card the grid kept the nav column (60px) and the list (288px) beside `main` at any
 * width, so at 390px `main` was ~42px, the editor 0px and the page scrolled sideways. These are the
 * measurements that would have caught it, in a real browser: no horizontal scroll, a note wider than
 * 300px, the navigation reachable, and list -> note -> back working through real history.
 */
import { type Page } from '@playwright/test'

import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

const LONG_LINE = `const veryLongLineOfCode = someFunction(${'argumentNumber, '.repeat(12)}done)`

async function noHorizontalScroll(page: Page): Promise<void> {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
}

test('the phone layout: list and note are separate screens under a bottom nav', async ({
  authedPage: page,
  request,
}) => {
  const title = prefixedTitle('mobile')
  const note = await apiCreateNote(request, {
    title,
    body: `# ${title}\n\nA paragraph.\n\n\`\`\`ts\n${LONG_LINE}\n\`\`\`\n`,
    path: 'mobile/check.md',
  })

  try {
    await page.goto('/')

    // The list is the whole screen: search and New note, no note beside it, no tagline.
    await expect(page.getByTestId('search-input')).toBeVisible()
    await expect(page.getByTestId('new-note-button')).toBeVisible()
    await expect(page.locator('main')).toHaveCount(0)
    await expect(page.locator('.tagline')).toBeHidden()
    await noHorizontalScroll(page)

    // Bottom navigation: three destinations, along the bottom edge, each a touch target.
    const nav = page.getByTestId('nav-column')
    await expect(nav).toBeVisible()
    const viewport = page.viewportSize()!
    const navBox = (await nav.boundingBox())!
    expect(navBox.y + navBox.height).toBeGreaterThanOrEqual(viewport.height - 1)
    expect(navBox.width).toBeGreaterThanOrEqual(viewport.width - 1)
    for (const label of ['notes', 'graph', 'settings']) {
      const item = page.getByTestId(`nav-item-${label}`)
      await expect(item).toBeVisible()
      expect((await item.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
    await expect(page.getByTestId('nav-item-tokens')).toHaveCount(0)
    expect((await page.getByTestId('new-note-button').boundingBox())!.height).toBeGreaterThanOrEqual(44)

    // list -> note
    await page.getByRole('link', { name: title }).first().click()
    await expect(page).toHaveURL(new RegExp(`/notes/${note.ref}$`))
    await expect(page.getByTestId('title-input')).toHaveValue(title)
    await expect(page.locator('.sidebar')).toHaveCount(0)
    expect((await page.getByTestId('title-input').boundingBox())!.width).toBeGreaterThanOrEqual(300)
    expect((await page.locator('.editor-host').boundingBox())!.width).toBeGreaterThanOrEqual(300)
    await noHorizontalScroll(page)
    await expect(nav).toBeVisible()

    // The links/history rail is behind a control, not squashing the document beside it.
    await expect(page.locator('.right-rail')).toHaveCount(0)
    await page.getByTestId('toggle-details').click()
    await expect(page.locator('.right-rail')).toBeVisible()
    await noHorizontalScroll(page)
    await page.getByTestId('toggle-details').click()

    // note -> list, by the browser's back button and by the on-screen arrow.
    await page.goBack()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByTestId('search-input')).toBeVisible()

    await page.getByRole('link', { name: title }).first().click()
    await expect(page.getByTestId('title-input')).toHaveValue(title)
    await page.getByTestId('back-to-list').click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByTestId('search-input')).toBeVisible()

    // Settings links to Tokens and the pandan connection (both still routes of their own).
    await page.getByTestId('nav-item-settings').click()
    await expect(page.getByTestId('settings-page')).toBeVisible()
    await noHorizontalScroll(page)
    await page.getByTestId('settings-tokens').click()
    await expect(page).toHaveURL(/\/tokens$/)
    await noHorizontalScroll(page)
    await expect(page.getByTestId('nav-item-settings')).toHaveAttribute('aria-current', 'page')
    await page.goBack()
    await page.getByTestId('settings-pandan').click()
    await expect(page).toHaveURL(/\/pandan$/)
    await noHorizontalScroll(page)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('no authed route scrolls sideways, at the narrowest supported width', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle('mobile-narrow'),
    body: `\`\`\`\n${LONG_LINE}\n\`\`\`\n`,
  })
  try {
    await page.setViewportSize({ width: 320, height: 640 })
    for (const path of ['/', `/notes/${note.ref}`, '/graph', '/settings', '/tokens', '/pandan', '/device']) {
      await page.goto(path)
      await expect(page.getByTestId('nav-column')).toBeVisible()
      await noHorizontalScroll(page)
    }
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
