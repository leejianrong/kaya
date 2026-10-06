/**
 * KAN-1826: editing on a phone. Runs only in the `mobile` project (iPhone 13 profile, 390px wide,
 * touch).
 *
 * What this proves is the toolbar's behaviour in a real browser engine with a touch pointer: it
 * shows with the editor focused, its buttons change the document, and tapping one never takes focus
 * from the editor (which is what keeps a soft keyboard open). What it cannot prove is a real iOS or
 * Android keyboard: Chromium has none. The keyboard's effect on `visualViewport` is emulated by
 * replacing `window.visualViewport` with a controllable stand-in before the page loads, so the
 * inset arithmetic's wiring (toolbar position, editor padding, caret reveal) runs for real while the
 * numbers are ours.
 */
import { type Page } from '@playwright/test'

import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

/** Replace `visualViewport` with an event target the test can resize, like a keyboard would. */
async function fakeKeyboard(page: Page): Promise<void> {
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
}

async function setKeyboard(page: Page, px: number): Promise<void> {
  await page.evaluate((value) => (window as unknown as { __keyboard(px: number): void }).__keyboard(value), px)
}

async function docText(page: Page): Promise<string> {
  return page.locator('.cm-content').innerText()
}

async function editorHasFocus(page: Page): Promise<boolean> {
  return page.evaluate(() => document.activeElement?.closest('.cm-content') != null)
}

async function openInEdit(page: Page, ref: string): Promise<void> {
  await page.goto(`/notes/${ref}`)
  await page.getByTestId('mode-edit').click()
  await page.locator('.cm-content').tap()
  await expect(page.getByTestId('editor-toolbar')).toBeVisible()
}

test('the toolbar shows while editing with focus, and not in Read or after the editor loses focus', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle('toolbar-visible'),
    body: 'hello world\n',
  })
  try {
    await page.goto(`/notes/${note.ref}`)
    await expect(page.getByTestId('editor-toolbar')).toHaveCount(0)

    await page.getByTestId('mode-edit').click()
    await expect(page.getByTestId('editor-toolbar')).toHaveCount(0)
    await page.locator('.cm-content').tap()
    const toolbar = page.getByTestId('editor-toolbar')
    await expect(toolbar).toBeVisible()
    await expect(toolbar).toHaveAttribute('role', 'toolbar')

    // Eight plain buttons, each with a name, each a touch target, none wider than the screen.
    const names = ['Bold', 'Italic', 'Bulleted list', 'Checkbox list', 'Code', 'Link', 'Wikilink', 'Undo']
    for (const name of names) {
      const button = toolbar.getByRole('button', { name, exact: true })
      await expect(button).toBeVisible()
      const box = (await button.boundingBox())!
      expect(box.height).toBeGreaterThanOrEqual(44)
      expect(box.width).toBeGreaterThanOrEqual(40)
    }
    const toolbarBox = (await toolbar.boundingBox())!
    const viewport = page.viewportSize()!
    expect(toolbarBox.x).toBeGreaterThanOrEqual(0)
    expect(toolbarBox.x + toolbarBox.width).toBeLessThanOrEqual(viewport.width)
    expect(Math.round(toolbarBox.y + toolbarBox.height)).toBe(viewport.height)

    // It takes the bottom edge from the navigation bar while it is up, and gives it back.
    await expect(page.getByTestId('nav-column')).toBeHidden()

    // The title and path step aside for the keyboard; Save and the mode switch stay.
    await expect(page.getByTestId('title-input')).toBeHidden()
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible()

    // Read is how a phone leaves editing: no toolbar, and the navigation and title are back.
    await page.getByTestId('mode-read').tap()
    await expect(page.getByTestId('editor-toolbar')).toHaveCount(0)
    await expect(page.getByTestId('nav-column')).toBeVisible()
    await expect(page.getByTestId('title-input')).toBeVisible()

    // Back in Edit, nothing has focus yet, so there is no toolbar until the editor is tapped.
    await page.getByTestId('mode-edit').tap()
    await expect(page.getByTestId('editor-toolbar')).toHaveCount(0)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('tapping a button formats the text and leaves focus in the editor', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle('toolbar-format'),
    body: 'hello world\n',
  })
  try {
    await openInEdit(page, note.ref)
    const tool = (name: string) => page.getByTestId('editor-toolbar').getByRole('button', { name, exact: true })

    // Count every time the editor loses focus. `run` refocuses as a safety net, so the end state
    // alone cannot tell a button that refused focus from one that took it and gave it back.
    await page.evaluate(() => {
      const w = window as unknown as { __blurs: number }
      w.__blurs = 0
      document.addEventListener(
        'focusout',
        (event) => {
          if ((event.target as Element).closest?.('.cm-content')) w.__blurs += 1
        },
        true,
      )
    })

    // Select the first word: Home, then shift-right x5.
    await page.keyboard.press('Control+Home')
    for (let i = 0; i < 5; i += 1) {
      await page.keyboard.press('Shift+ArrowRight')
    }
    await tool('Bold').tap()
    expect(await docText(page)).toContain('**hello** world')
    expect(await editorHasFocus(page)).toBe(true)
    await expect(page.getByTestId('editor-toolbar')).toBeVisible()

    // One tap is one undo step.
    await tool('Undo').tap()
    expect(await docText(page)).toContain('hello world')
    expect(await docText(page)).not.toContain('**')
    expect(await editorHasFocus(page)).toBe(true)
    await tool('Bold').tap()
    expect(await docText(page)).toContain('**hello** world')

    // Toggling back removes it.
    await tool('Bold').tap()
    expect(await docText(page)).toContain('hello world')
    expect(await docText(page)).not.toContain('**')

    // A mouse-style click does not take focus either.
    await tool('Italic').click()
    expect(await docText(page)).toContain('*hello* world')
    expect(await editorHasFocus(page)).toBe(true)

    // Line formats on the caret line.
    await page.keyboard.press('Control+End')
    await page.keyboard.type('task')
    await tool('Checkbox list').tap()
    expect(await docText(page)).toContain('- [ ] task')
    await tool('Checkbox list').tap()
    await tool('Bulleted list').tap()
    expect(await docText(page)).toMatch(/^- task$/m)
    await tool('Bulleted list').tap()
    expect(await docText(page)).toMatch(/^task$/m)

    // Link: wraps the selection and leaves the caret in the address.
    await page.keyboard.press('Shift+Home')
    await tool('Link').tap()
    await page.keyboard.type('https://example.com')
    expect(await docText(page)).toContain('[task](https://example.com)')

    // Code at a caret that is not on a word opens an empty pair.
    await page.keyboard.press('Control+Home')
    await tool('Code').tap()
    expect(await docText(page)).toContain('``*hello*')

    // Not once, in all of the above taps and clicks, did the editor lose focus.
    expect(await page.evaluate(() => (window as unknown as { __blurs: number }).__blurs)).toBe(0)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('the wikilink button opens title completion and does not double the closing brackets', async ({
  authedPage: page,
  request,
}) => {
  const target = await apiCreateNote(request, {
    title: prefixedTitle('wikilink-target'),
    body: 'x\n',
  })
  const note = await apiCreateNote(request, { title: prefixedTitle('wikilink-source'), body: 'see ' })
  try {
    await openInEdit(page, note.ref)
    await page.keyboard.press('Control+End')
    await page.getByTestId('editor-toolbar').getByRole('button', { name: 'Wikilink' }).tap()
    expect(await docText(page)).toContain('see [[')

    const list = page.locator('.cm-tooltip-autocomplete')
    await expect(list).toBeVisible()
    await page.keyboard.type(target.title)
    await expect(list.getByText(target.title).first()).toBeVisible()
    await page.keyboard.press('Enter')
    const text = await docText(page)
    expect(text).toContain(`see [[${target.title}]]`)
    expect(text).not.toContain(']]]]')
    expect(await editorHasFocus(page)).toBe(true)

    // A selection is wrapped whole, with nothing left to complete.
    await page.keyboard.press('Control+A')
    await page.keyboard.type('Plain')
    await page.keyboard.press('Control+A')
    await page.getByTestId('editor-toolbar').getByRole('button', { name: 'Wikilink' }).tap()
    expect(await docText(page)).toContain('[[Plain]]')
    await expect(page.locator('.cm-tooltip-autocomplete')).toHaveCount(0)
  } finally {
    await apiDeleteNote(request, note.ref)
    await apiDeleteNote(request, target.ref)
  }
})

test('the toolbar rides above the keyboard and the caret stays in view', async ({
  authedPage: page,
  request,
}) => {
  await fakeKeyboard(page)
  const lines = Array.from({ length: 60 }, (_, i) => `line ${i + 1}`).join('\n')
  const note = await apiCreateNote(request, { title: prefixedTitle('toolbar-keyboard'), body: lines })
  try {
    await openInEdit(page, note.ref)
    const viewport = page.viewportSize()!
    const toolbar = page.getByTestId('editor-toolbar')

    await setKeyboard(page, 300)
    await expect.poll(async () => Math.round((await toolbar.boundingBox())!.y + (await toolbar.boundingBox())!.height)).toBe(viewport.height - 300)

    // The editor's own box ends where the toolbar starts, so nothing of it is under the keyboard.
    const host = (await page.locator('.editor-host').boundingBox())!
    const bar = (await toolbar.boundingBox())!
    expect(host.y + host.height, JSON.stringify({ host, bar })).toBeLessThanOrEqual(bar.y + 1)

    // The caret sent to the end of a long document is on screen: the last line sits above the
    // toolbar (CodeMirror draws the native caret, so the line is what can be measured).
    await page.keyboard.press('Control+End')
    await expect
      .poll(async () => {
        const last = (await page.locator('.cm-line').last().boundingBox())!
        return Math.round(last.y + last.height - (await toolbar.boundingBox())!.y)
      })
      .toBeLessThanOrEqual(0)
    await expect(page.locator('.cm-line').last()).toHaveText('line 60')

    // Keyboard away: back to the bottom edge.
    await setKeyboard(page, 0)
    await expect.poll(async () => Math.round((await toolbar.boundingBox())!.y + (await toolbar.boundingBox())!.height)).toBe(viewport.height)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('Save belongs to editing: absent in Read, present in Edit, and Read says so when text is unsaved', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, { title: prefixedTitle('save-only-edit'), body: 'text\n' })
  try {
    await page.goto(`/notes/${note.ref}`)
    await expect(page.getByTestId('mode-read')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0)

    await page.getByTestId('mode-edit').click()
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible()
    await page.locator('.cm-content').tap()
    await page.keyboard.type('more')

    await page.getByTestId('mode-read').click()
    await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0)
    await expect(page.getByTestId('read-unsaved')).toBeVisible()

    await page.getByTestId('mode-edit').click()
    await expect(page.getByTestId('read-unsaved')).toHaveCount(0)
    await page.getByRole('button', { name: 'Save' }).tap()
    await expect(page.getByTestId('save-state')).toHaveText(/saved/)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('editor and path text are 16px on a phone, so iOS does not zoom on focus', async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, { title: prefixedTitle('font16'), body: 'text\n' })
  try {
    await page.goto(`/notes/${note.ref}`)
    await page.getByTestId('mode-edit').click()
    await expect(page.locator('.cm-content')).toBeVisible()
    for (const selector of ['.cm-editor', '.cm-content', '[data-testid="path-input"]']) {
      const size = await page.locator(selector).first().evaluate((el) => getComputedStyle(el).fontSize)
      expect(size, selector).toBe('16px')
    }
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
