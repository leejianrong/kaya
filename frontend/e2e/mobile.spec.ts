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
      // KAN-1822: each destination has its icon above the label.
      await expect(item.locator('svg')).toHaveCount(1)
    }
    await expect(page.getByTestId('nav-item-tokens')).toHaveCount(0)
    expect((await page.getByTestId('new-note-button').boundingBox())!.height).toBeGreaterThanOrEqual(44)

    // list -> note
    await page.getByRole('link', { name: title }).first().click()
    await expect(page).toHaveURL(new RegExp(`/notes/${note.ref}$`))
    await expect(page.getByTestId('title-input')).toHaveValue(title)
    await expect(page.locator('.sidebar')).toHaveCount(0)
    expect((await page.getByTestId('title-input').boundingBox())!.width).toBeGreaterThanOrEqual(300)
    // KAN-1819: a saved note opens in Read — the rendered note, not the editor.
    await expect(page.getByTestId('mode-read')).toHaveAttribute('aria-pressed', 'true')
    expect((await page.getByTestId('preview').boundingBox())!.width).toBeGreaterThanOrEqual(300)
    await noHorizontalScroll(page)
    await expect(nav).toBeVisible()

    // KAN-1827: backlinks and history are behind the Links button, in a sheet, not squashing the
    // document. The sheet's own behaviour is in `mobile-links-sheet.spec.ts`.
    await expect(page.locator('.right-rail')).toHaveCount(0)
    await page.getByTestId('toggle-details').click()
    await expect(page.getByRole('dialog', { name: 'Links and history' })).toBeVisible()
    await noHorizontalScroll(page)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)

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

test('Read / Edit on a phone: a saved note opens in Read, Split is absent, Edit has the editor and Save', async ({
  authedPage: page,
  request,
}) => {
  const title = prefixedTitle('mobile-modes')
  const note = await apiCreateNote(request, {
    title,
    body: `# ${title}\n\nProse.\n\n\`\`\`ts\n${LONG_LINE}\n\`\`\`\n`,
  })
  try {
    await page.goto(`/notes/${note.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(title)

    // Read: the document alone; no editor, Save or Delete; the title and ref still read as a heading.
    await expect(page.getByTestId('mode-read')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('mode-split')).toHaveCount(0)
    await expect(page.getByTestId('toggle-preview')).toHaveCount(0)
    // KAN-1824: the body's own H1 repeats the title, so Read drops it; the title shows once, above.
    await expect(page.getByTestId('preview').locator('h1')).toHaveCount(0)
    await expect(page.getByTestId('preview')).toContainText('Prose.')
    await expect(page.locator('.editor-host')).toBeHidden()
    await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0)
    await expect(page.getByTestId('delete-button')).toHaveCount(0)
    await noHorizontalScroll(page)

    // The segments are touch targets and the control spans the screen.
    const switchBox = (await page.getByTestId('mode-switch').boundingBox())!
    expect(switchBox.width).toBeGreaterThanOrEqual(page.viewportSize()!.width - 40)
    for (const mode of ['read', 'edit']) {
      expect((await page.getByTestId(`mode-${mode}`).boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }

    // Edit: the editor at full width, with Save and Delete.
    await page.getByTestId('mode-edit').click()
    await expect(page.getByTestId('mode-edit')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('preview')).toHaveCount(0)
    await expect(page.locator('.cm-content')).toBeVisible()
    expect((await page.locator('.editor-host').boundingBox())!.width).toBeGreaterThanOrEqual(300)
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible()
    await expect(page.getByTestId('delete-button')).toBeVisible()
    await noHorizontalScroll(page)

    // And the choice is remembered for the phone: the next note opens in Edit.
    await page.reload()
    await expect(page.getByTestId('mode-edit')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('.cm-content')).toBeVisible()
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('a note just created through New note opens in Edit, even when Read is what is remembered', async ({
  authedPage: page,
  request,
}) => {
  const title = prefixedTitle('mobile-new')
  const existing = await apiCreateNote(request, { title: prefixedTitle('mobile-existing'), body: 'x\n' })
  try {
    // Remember Read for this size class.
    await page.goto(`/notes/${existing.ref}`)
    await page.getByTestId('mode-read').click()
    await page.getByTestId('back-to-list').click()

    await page.getByTestId('new-note-button').click()
    await expect(page).toHaveURL(/\/notes\/NOTE-\d+$/)
    // KAY-166: the title is focused and selected, so typing names the note; Enter drops into the body.
    await expect(page.getByTestId('title-input')).toBeFocused()
    await page.keyboard.type(title)
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('mode-edit')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('.cm-content')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible()
    await noHorizontalScroll(page)

    // Enter in the title moved focus into the body: typing works with nothing to tap.
    await expect(page.locator('.cm-content')).toBeFocused()
    await page.keyboard.type('hello')
    await expect(page.getByTestId('save-state')).toHaveText(/unsaved changes/)

    const ref = new URL(page.url()).pathname.split('/').pop()!
    await apiDeleteNote(request, ref)
  } finally {
    await apiDeleteNote(request, existing.ref)
  }
})

test('no mode scrolls sideways on a phone', async ({ authedPage: page, request }) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle('mobile-modes-scroll'),
    body: `\`\`\`\n${LONG_LINE}\n\`\`\`\n\n${'word '.repeat(200)}\n`,
  })
  try {
    await page.goto(`/notes/${note.ref}`)
    for (const mode of ['edit', 'read']) {
      await page.getByTestId(`mode-${mode}`).click()
      await expect(page.getByTestId(`mode-${mode}`)).toHaveAttribute('aria-pressed', 'true')
      await noHorizontalScroll(page)
    }
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
