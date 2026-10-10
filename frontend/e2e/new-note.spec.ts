/**
 * KAY-166: "New note" is instant and Obsidian-shaped. The button creates `Untitled` in the current
 * folder, opens it in Edit with the title selected and focused, typing names it, and Enter moves the
 * caret into the body. Two creates in a row get distinct titles; an active search is cleared.
 */
import { runId } from './env'
import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

test('new note: instant Untitled in the open note folder, title focused, Enter goes to the body', async ({
  authedPage: page,
  request,
}) => {
  const folder = `${runId()}-newnote`
  const seed = await apiCreateNote(request, {
    title: prefixedTitle('new-note seed'),
    path: `${folder}/seed.md`,
    body: 'seed\n',
  })
  const created: string[] = []
  try {
    await page.goto(`/notes/${seed.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(seed.title)

    // First create: Untitled-ish, in the seed's folder, title focused and selected.
    await page.getByTestId('new-note-button').click()
    await expect(page).not.toHaveURL(new RegExp(`/notes/${seed.ref}$`))
    await expect(page.getByTestId('title-input')).toBeFocused()
    const first = await page.getByTestId('title-input').inputValue()
    expect(first).toMatch(/^Untitled( \d+)?$/)
    await expect(page.getByTestId('path-input')).toHaveValue(
      new RegExp(`^${folder}/untitled(-\\d+)?\\.md$`),
    )
    created.push(new URL(page.url()).pathname.split('/').pop()!)

    // The sidebar already shows it, and the folder is the seed's.
    await expect(page.getByRole('link', { name: first, exact: false }).first()).toBeVisible()

    // Typing replaces the selected title; Enter lands in the body.
    const named = prefixedTitle('new-note first')
    await page.keyboard.type(named)
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('title-input')).toHaveValue(named)
    await expect(page.locator('.editor-host .cm-content')).toBeFocused()

    // Second create right after: still in the folder, and a different title from the first's slot.
    await page.getByTestId('new-note-button').click()
    await expect(page.getByTestId('title-input')).toBeFocused()
    await expect(page.getByTestId('title-input')).toHaveValue(/^Untitled( \d+)?$/)
    await expect(page.getByTestId('path-input')).toHaveValue(
      new RegExp(`^${folder}/untitled(-\\d+)?\\.md$`),
    )
    created.push(new URL(page.url()).pathname.split('/').pop()!)
    await page.keyboard.type(prefixedTitle('new-note second'))
    await page.keyboard.press('Enter')
    await expect(page.locator('.editor-host .cm-content')).toBeFocused()
  } finally {
    for (const ref of created) {
      await apiDeleteNote(request, ref)
    }
    await apiDeleteNote(request, seed.ref)
  }
})

test('new note clears an active search so the new row is visible', async ({
  authedPage: page,
  request,
}) => {
  const seed = await apiCreateNote(request, { title: prefixedTitle('new-note search seed'), body: 'x\n' })
  let ref: string | null = null
  try {
    await page.goto('/')
    await page.getByTestId('search-input').fill('new-note search seed')
    await page.getByTestId('search-input').press('Enter')
    await expect(page.getByTestId('search-ordering')).toBeVisible()

    await page.getByTestId('new-note-button').click()
    await expect(page).toHaveURL(/\/notes\/NOTE-\d+$/)
    ref = new URL(page.url()).pathname.split('/').pop()!
    await expect(page.getByTestId('search-input')).toHaveValue('')
    await expect(page.getByTestId('search-ordering')).toHaveCount(0)
    await expect(page.locator(`a[href="/notes/${ref}"]`).first()).toBeVisible()
    // Name it so the run's teardown sweep can find it if the delete below is skipped.
    await page.keyboard.type(prefixedTitle('new-note searched'))
    await page.keyboard.press('Enter')
  } finally {
    if (ref !== null) {
      await apiDeleteNote(request, ref)
    }
    await apiDeleteNote(request, seed.ref)
  }
})
