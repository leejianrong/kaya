/**
 * KAN-1815: the Settings toggle, then a save. Needs KAN-1814's server-side formatter on the wire —
 * with the toggle ON the stored body must come back formatted, with it OFF byte-for-byte as typed.
 *
 * Drives the real UI: the nav column's Settings link, the checkbox, CM6's own contenteditable via
 * real keyboard events, the Save button, and a reload to prove the choice and the body both
 * persisted server-side. The account is put back to the default (ON) at the end of each test,
 * because every e2e test in this suite shares one account.
 */
import { type Page } from '@playwright/test'

import { fakeToken } from './env'
import { expect, prefixedTitle, test } from './fixtures'

/** Markdown the formatter visibly changes: heading spacing, list markers, a missing blank line. */
const UNFORMATTED = ['#   Title', '*  one', '*  two'].join('\n')

async function setPreference(page: Page, value: boolean): Promise<void> {
  const response = await page.request.patch('/api/v1/preferences', {
    headers: { Authorization: `Bearer ${fakeToken()}` },
    data: { format_on_save: value },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

async function storedBody(page: Page, ref: string): Promise<string> {
  const response = await page.request.get(`/api/v1/notes/${encodeURIComponent(ref)}`, {
    headers: { Authorization: `Bearer ${fakeToken()}` },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { body: string }).body
}

async function createAndType(page: Page, title: string): Promise<string> {
  await page.getByTestId('new-note-button').click()
  await page.getByTestId('create-title-input').fill(title)
  await page.getByTestId('create-confirm').click()
  await expect(page.getByTestId('title-input')).toHaveValue(title)
  const ref = new URL(page.url()).pathname.split('/').pop()!

  await page.locator('.editor-host .cm-content').click()
  for (const [index, line] of UNFORMATTED.split('\n').entries()) {
    if (index > 0) {
      await page.keyboard.press('Enter')
    }
    await page.keyboard.type(line)
  }
  return decodeURIComponent(ref)
}

test.afterEach(async ({ page }) => {
  await setPreference(page, true)
})

test('the toggle defaults ON, and turning it OFF persists across a reload', async ({
  authedPage: page,
}) => {
  await page.getByTestId('nav-item-settings').click()
  const toggle = page.getByTestId('format-on-save')
  await expect(toggle).toBeChecked()
  await expect(page.getByTestId('format-on-save-help')).toContainText(
    'CLI and MCP never format implicitly',
  )

  await toggle.uncheck()
  await expect.poll(async () => {
    const response = await page.request.get('/api/v1/preferences', {
      headers: { Authorization: `Bearer ${fakeToken()}` },
    })
    return ((await response.json()) as { format_on_save: boolean }).format_on_save
  }).toBe(false)

  await page.reload()
  await expect(page.getByTestId('format-on-save')).not.toBeChecked()
})

test('ON: saving an unformatted note stores the formatted body, in place', async ({
  authedPage: page,
}) => {
  const ref = await createAndType(page, prefixedTitle('format-on'))
  const editor = page.locator('.editor-host .cm-content')

  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-state')).toHaveText(/^saved · now at /)

  const stored = await storedBody(page, ref)
  expect(stored).not.toBe(UNFORMATTED)
  expect(stored).toContain('# Title')
  // The editor shows what was stored, without a reload and without a second save.
  await expect(editor).toContainText('# Title')
  await expect(editor).not.toContainText('#   Title')
  await expect(page.getByTestId('save-state')).toHaveText(/^saved · now at /)
})

test('OFF: saving stores the body byte-for-byte as typed', async ({ authedPage: page }) => {
  await page.getByTestId('nav-item-settings').click()
  await page.getByTestId('format-on-save').uncheck()
  await expect(page.getByTestId('format-on-save')).not.toBeChecked()
  await page.getByTestId('nav-item-notes').click()

  const ref = await createAndType(page, prefixedTitle('format-off'))

  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByTestId('save-state')).toHaveText(/^saved · now at /)

  expect(await storedBody(page, ref)).toBe(UNFORMATTED)
})
