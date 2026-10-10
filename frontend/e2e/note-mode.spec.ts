/**
 * KAN-1819: the Read | Edit | Split switch at desktop width (the `chromium` project, 1280px).
 * The phone half is in `mobile.spec.ts`.
 *
 * The default here is Edit (the maintainer's call for expanded), switching to Read hides the editor
 * and shows the preview alone, Split puts both side by side at roughly 55/45, and the choice
 * survives a reload — remembered per size class in `localStorage`.
 */
import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

test('desktop: Edit by default, Read alone, Split at 55/45, and the choice survives a reload', async ({
  authedPage: page,
  request,
}) => {
  const title = prefixedTitle('modes')
  const note = await apiCreateNote(request, {
    title,
    body: `# Heading of ${title}\n\n${'A paragraph of prose that keeps going. '.repeat(60)}\n`,
    path: 'modes/check.md',
  })
  try {
    // Wide enough that the Read measure (75ch) is much narrower than the pane.
    await page.setViewportSize({ width: 1700, height: 900 })
    await page.goto(`/notes/${note.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(title)
    const editor = page.locator('.editor-host')
    const preview = page.getByTestId('preview')

    // Default: Edit — the editor alone, the old header toggle gone.
    await expect(page.getByTestId('mode-edit')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('toggle-preview')).toHaveCount(0)
    await expect(editor).toBeVisible()
    await expect(preview).toHaveCount(0)
    // KAN-1997: Edit fills the pane; there is no measure cap on the editor.
    const main = (await page.locator('main').boundingBox())!
    const pane = (await page.locator('section.pane[aria-label="Editor"]').boundingBox())!
    expect(pane.width).toBeGreaterThan(main.width - 80)

    // Read: the rendered note alone, a full-width pane with a ~75ch text measure, the editor hidden (and out of the a11y tree).
    await page.getByTestId('mode-read').click()
    await expect(page.getByTestId('mode-read')).toHaveAttribute('aria-pressed', 'true')
    await expect(preview).toBeVisible()
    await expect(preview.locator('h1')).toHaveText(`Heading of ${title}`)
    await expect(editor).toBeHidden()
    await expect(page.getByTestId('delete-button')).toHaveCount(0)
    // The pane is full width, but running text keeps its ~75ch measure.
    const read = (await page.locator('.preview').boundingBox())!
    expect(read.width).toBeGreaterThan(main.width - 80)
    const prose = (await preview.locator('p').first().boundingBox())!
    expect(prose.width).toBeLessThanOrEqual(900)
    expect(prose.width).toBeLessThan(main.width * 0.7)

    // "Full-width reading" (Settings, per browser) removes the cap.
    await page.evaluate(() => localStorage.setItem('kaya.reading.fullWidth', '1'))
    await page.reload()
    await expect(page.getByTestId('preview')).toBeVisible()
    const wide = (await preview.locator('p').first().boundingBox())!
    expect(wide.width).toBeGreaterThan(main.width - 120)
    await page.evaluate(() => localStorage.removeItem('kaya.reading.fullWidth'))
    await page.reload()
    await expect(page.getByTestId('preview')).toBeVisible()

    // Split: both, the editor ~55% and the preview ~45% of the pair.
    await page.getByTestId('mode-split').click()
    await expect(editor).toBeVisible()
    await expect(preview).toBeVisible()
    const left = (await page.locator('section.pane[aria-label="Editor"]').boundingBox())!
    const right = (await page.locator('.preview').boundingBox())!
    const ratio = left.width / (left.width + right.width)
    expect(ratio).toBeGreaterThan(0.52)
    expect(ratio).toBeLessThan(0.58)

    // The choice is remembered: a reload comes back in Split.
    await page.reload()
    await expect(page.getByTestId('title-input')).toHaveValue(title)
    await expect(page.getByTestId('mode-split')).toHaveAttribute('aria-pressed', 'true')
    await expect(preview).toBeVisible()
    await expect(editor).toBeVisible()
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('desktop: typing in Edit shows in Read without saving, and Split follows keystrokes', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle('modes-live'),
    body: 'start\n',
  })
  try {
    await page.goto(`/notes/${note.ref}`)
    await page.getByTestId('mode-edit').click()
    await page.locator('.cm-content').click()
    await page.keyboard.press('Control+A')
    await page.keyboard.type('# Typed live')

    await page.getByTestId('mode-read').click()
    await expect(page.getByTestId('preview').locator('h1')).toHaveText('Typed live')
    // KAN-1826: Read has no Save and no Delete. Unsaved text is still said out loud.
    await expect(page.getByTestId('read-unsaved')).toContainText('Switch to Edit to save')
    await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0)
    await expect(page.getByTestId('delete-button')).toHaveCount(0)

    await page.getByTestId('mode-edit').click()
    await expect(page.getByTestId('save-state')).toHaveText(/unsaved changes/)
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible()
    await expect(page.locator('.cm-content')).toContainText('# Typed live')
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('desktop: Split falls back to Edit when the window shrinks below it, and the segment hides', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, { title: prefixedTitle('modes-shrink'), body: 'x\n' })
  try {
    await page.goto(`/notes/${note.ref}`)
    await page.getByTestId('mode-split').click()
    await expect(page.getByTestId('preview')).toBeVisible()

    await page.setViewportSize({ width: 700, height: 800 })
    await expect(page.getByTestId('mode-split')).toHaveCount(0)
    await expect(page.getByTestId('mode-edit')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('preview')).toHaveCount(0)
    await expect(page.locator('.editor-host')).toBeVisible()
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('desktop: the editor keeps its own size, the 16px phone rule does not reach it (KAN-1826)', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, { title: prefixedTitle('desktop-font'), body: 'text\n' })
  try {
    await page.goto(`/notes/${note.ref}`)
    await expect(page.locator('.cm-content')).toBeVisible()
    const size = await page.locator('.cm-editor').evaluate((el) => getComputedStyle(el).fontSize)
    expect(size).not.toBe('16px')
    // And no toolbar at this width, focused or not.
    await page.locator('.cm-content').click()
    await expect(page.getByTestId('editor-toolbar')).toHaveCount(0)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
