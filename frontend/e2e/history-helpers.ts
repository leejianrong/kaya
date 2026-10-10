/** Shared by the two KAY-138 history specs (not itself a spec, so Playwright never runs it). */
import { type Page } from '@playwright/test'

import { apiCreateNote, apiUpdateNote, expect, prefixedTitle } from './fixtures'

export async function seedThreeVersions(page: Page, request: Parameters<typeof apiCreateNote>[0]) {
  const note = await apiCreateNote(request, {
    title: prefixedTitle('actor'),
    body: 'alpha\nbeta\ngamma\n',
  })
  const edited = await apiUpdateNote(request, note.ref, {
    body: 'alpha\nbeta changed\ngamma\ndelta\n',
    if_updated_at: note.updated_at,
  })
  const response = await page.request.patch(`/api/v1/notes/${encodeURIComponent(note.ref)}`, {
    data: { body: 'alpha\nbeta changed\ngamma\ndelta\nepsilon\n', if_updated_at: edited.updated_at },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return note
}

export async function shoot(page: Page, name: string): Promise<void> {
  const dir = process.env.KAYA_SHOT_DIR
  if (!dir) {
    return
  }
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    await page.screenshot({ path: `${dir}/${name}-${scheme}.png` })
  }
}
