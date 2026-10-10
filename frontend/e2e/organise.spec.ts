/**
 * KAY-168: organise from the tree. Move a note (drag, and the row menu), a client-only new folder
 * that becomes real only when a note lands in it, rename a note and a folder, an invalid folder
 * name, and the keyboard-only path through the menu. Notes live under run-prefixed folders so the
 * suite's teardown (and other specs' trees) are unaffected.
 */
import type { APIRequestContext, Page } from '@playwright/test'

import { runId } from './env'
import { apiCreateNote, apiDeleteNote, expect, prefixedTitle, test } from './fixtures'

const folderRow = (page: Page, key: string) => page.locator(`button.row.folder[data-id="${key}"]`)
const noteRow = (page: Page, ref: string) => page.locator(`a.row.note[data-id="${ref}"]`)

async function seed(request: APIRequestContext, root: string, count: number, name: string) {
  const made = []
  for (let n = 1; n <= count; n += 1) {
    made.push(
      await apiCreateNote(request, {
        title: prefixedTitle(`${name} ${n}`),
        path: `${root}/src/${name}-${n}.md`,
        body: `${name} ${n}\n`,
      }),
    )
  }
  return made
}

async function listPaths(page: Page): Promise<Record<string, string>> {
  return page.evaluate(async () => {
    const token = sessionStorage.getItem('kaya.token')
    const response = await fetch('/api/v1/notes', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'same-origin',
    })
    const body = (await response.json()) as { notes: { ref: string; path: string }[] }
    return Object.fromEntries(body.notes.map((note) => [note.ref, note.path]))
  })
}

test('drag a note onto a folder moves it with one PATCH to path, and the tree announces it', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-drag`
  const [mover] = await seed(request, root, 1, 'mover')
  const target = await apiCreateNote(request, {
    title: prefixedTitle('drag target'),
    path: `${root}/dest/target.md`,
  })
  try {
    await page.goto('/')
    await expect(noteRow(page, mover.ref)).toBeVisible()

    const patches: string[] = []
    page.on('request', (req) => {
      if (req.method() === 'PATCH') patches.push(req.postData() ?? '')
    })

    await noteRow(page, mover.ref).dragTo(folderRow(page, `${root}/dest`))

    await expect(page.getByTestId('tree-toast')).toContainText(`to ${root}/dest`)
    expect(patches).toEqual([JSON.stringify({ path: `${root}/dest/mover-1.md` })])
    await expect(
      page.locator(`li:has(> button[data-id="${root}/dest"]) a[data-id="${mover.ref}"]`),
    ).toBeVisible()
    expect((await listPaths(page))[mover.ref]).toBe(`${root}/dest/mover-1.md`)
  } finally {
    await apiDeleteNote(request, mover.ref)
    await apiDeleteNote(request, target.ref)
  }
})

test('Move to... from the row menu lists folders, omits the current one, and offers the top level', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-menu`
  const [note] = await seed(request, root, 1, 'menu-note')
  const other = await apiCreateNote(request, {
    title: prefixedTitle('menu other'),
    path: `${root}/other/o.md`,
  })
  try {
    await page.goto('/')
    await noteRow(page, note.ref).hover()
    await page.locator(`li:has(> a[data-id="${note.ref}"]) > .more`).click()
    const menu = page.getByRole('menu')
    await expect(menu.getByRole('menuitem')).toHaveText(['Move to…', 'Rename'])

    await menu.getByRole('menuitem', { name: 'Move to…' }).click()
    await expect(menu.getByRole('menuitem', { name: `${root}/src`, exact: true })).toHaveCount(0)
    await expect(menu.getByRole('menuitem', { name: 'Unfiled (top level)' })).toBeVisible()
    await menu.getByRole('menuitem', { name: `${root}/other`, exact: true }).click()

    await expect(page.getByTestId('tree-toast')).toContainText(`Moved`)
    expect((await listPaths(page))[note.ref]).toBe(`${root}/other/menu-note-1.md`)

    // And to the top level: the filename is kept.
    await page.locator(`li:has(> a[data-id="${note.ref}"]) > .more`).click({ force: true })
    await page.getByRole('menuitem', { name: 'Move to…' }).click()
    await page.getByRole('menuitem', { name: 'Unfiled (top level)' }).click()
    await expect.poll(async () => (await listPaths(page))[note.ref]).toBe('menu-note-1.md')
  } finally {
    await apiDeleteNote(request, note.ref)
    await apiDeleteNote(request, other.ref)
  }
})

test('a new folder is a placeholder until a note lands in it, and then it is real after a reload', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-newfolder`
  const [note] = await seed(request, root, 1, 'filler')
  try {
    await page.goto(`/notes/${note.ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(note.title)

    const posts: string[] = []
    page.on('request', (req) => {
      if (req.method() === 'POST') posts.push(req.url())
    })

    // The current folder is the open note's, so the placeholder is made inside it.
    await page.getByTestId('new-folder-button').click()
    const field = page.getByRole('textbox', { name: 'New folder name' })
    await expect(field).toBeFocused()
    await field.fill('ideas')
    await field.press('Enter')

    await expect(folderRow(page, `${root}/src/ideas`)).toBeVisible()
    await expect(page.getByText('Empty. Drag a note here, or create one.')).toBeVisible()
    await expect(page.getByTestId('tree-toast')).toContainText('stays until a note is placed in it')
    expect(posts).toEqual([]) // nothing was sent to the server

    // Move a note into it: the folder is real now.
    await noteRow(page, note.ref).dragTo(folderRow(page, `${root}/src/ideas`))
    await expect(page.getByText('Empty. Drag a note here, or create one.')).toHaveCount(0)
    await page.reload()
    await expect(folderRow(page, `${root}/src/ideas`)).toBeVisible()
    expect((await listPaths(page))[note.ref]).toBe(`${root}/src/ideas/filler-1.md`)

    // An empty placeholder does not survive a reload.
    await page.getByTestId('new-folder-button').click()
    await page.getByRole('textbox', { name: 'New folder name' }).fill('ephemeral')
    await page.keyboard.press('Enter')
    await expect(folderRow(page, `${root}/src/ideas/ephemeral`)).toBeVisible()
    await page.reload()
    await expect(folderRow(page, `${root}/src/ideas`)).toBeVisible()
    await expect(folderRow(page, `${root}/src/ideas/ephemeral`)).toHaveCount(0)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('rename a note: the title changes, the filename stays, via F2 and Enter', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-renote`
  const [note] = await seed(request, root, 1, 'rename-me')
  try {
    await page.goto('/')
    await noteRow(page, note.ref).focus()
    await page.keyboard.press('F2')
    const field = page.getByRole('textbox', { name: /^Rename / })
    await expect(field).toBeFocused()
    const renamed = prefixedTitle('renamed note')
    await field.fill(renamed)
    await field.press('Enter')

    await expect(noteRow(page, note.ref)).toContainText(renamed)
    await expect(noteRow(page, note.ref)).toContainText('rename-me-1.md')
    await expect(noteRow(page, note.ref)).toBeFocused()

    // Escape cancels.
    await page.keyboard.press('F2')
    await page.getByRole('textbox', { name: /^Rename / }).fill('should not stick')
    await page.keyboard.press('Escape')
    await expect(noteRow(page, note.ref)).toContainText(renamed)
    expect((await listPaths(page))[note.ref]).toBe(`${root}/src/rename-me-1.md`)
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})

test('rename a folder holding three notes: all follow, collapse state carries, the open note stays open', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-refolder`
  const notes = await seed(request, root, 3, 'inside')
  const sub = await apiCreateNote(request, {
    title: prefixedTitle('inside deeper'),
    path: `${root}/src/deep/d.md`,
  })
  try {
    await page.goto(`/notes/${notes[0].ref}`)
    await expect(page.getByTestId('title-input')).toHaveValue(notes[0].title)

    // Collapse the nested folder first: its closed state must follow the rename.
    await folderRow(page, `${root}/src/deep`).click()
    await expect(noteRow(page, sub.ref)).toHaveCount(0)

    await folderRow(page, `${root}/src`).dblclick()
    const field = page.getByRole('textbox', { name: /^Rename folder / })
    await field.fill('renamed')
    await field.press('Enter')

    await expect(page.getByTestId('tree-toast')).toContainText('4 notes')
    await expect(folderRow(page, `${root}/renamed`)).toBeVisible()
    await expect(folderRow(page, `${root}/src`)).toHaveCount(0)
    for (const note of notes) await expect(noteRow(page, note.ref)).toBeVisible()
    // The nested folder is still collapsed under its new key.
    await expect(folderRow(page, `${root}/renamed/deep`)).toHaveAttribute('aria-expanded', 'false')
    await expect(noteRow(page, sub.ref)).toHaveCount(0)

    // The route is unchanged (identity is the ref), and the open note's path field follows.
    await expect(page).toHaveURL(new RegExp(`/notes/${notes[0].ref}$`))
    await expect(page.getByTestId('path-input')).toHaveValue(`${root}/renamed/inside-1.md`)
    const paths = await listPaths(page)
    for (const [index, note] of notes.entries()) {
      expect(paths[note.ref]).toBe(`${root}/renamed/inside-${index + 1}.md`)
    }
    expect(paths[sub.ref]).toBe(`${root}/renamed/deep/d.md`)

    // The next guarded body save is not refused against the rename's own (restamping) write.
    const editor = page.locator('.editor-host .cm-content')
    await editor.click()
    await page.keyboard.type(' after rename')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByTestId('save-state')).toHaveText(/^saved/)
  } finally {
    for (const note of [...notes, sub]) await apiDeleteNote(request, note.ref)
  }
})

test('an invalid folder name is refused inline and nothing changes', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-invalid`
  const [note] = await seed(request, root, 1, 'keep')
  const sibling = await apiCreateNote(request, {
    title: prefixedTitle('sibling'),
    path: `${root}/other/s.md`,
  })
  try {
    await page.goto('/')
    await folderRow(page, `${root}/src`).press('F2')
    const field = page.getByRole('textbox', { name: /^Rename folder / })

    await field.fill('a/b')
    await field.press('Enter')
    await expect(page.getByRole('alert')).toContainText('cannot contain "/"')
    await expect(field).toBeFocused()

    await field.fill('   ')
    await field.press('Enter')
    await expect(page.getByRole('alert')).toContainText('needs a name')

    await field.fill('OTHER')
    await field.press('Enter')
    await expect(page.getByRole('alert')).toContainText('already exists')

    await field.press('Escape')
    await expect(folderRow(page, `${root}/src`)).toBeVisible()
    expect((await listPaths(page))[note.ref]).toBe(`${root}/src/keep-1.md`)
  } finally {
    await apiDeleteNote(request, note.ref)
    await apiDeleteNote(request, sibling.ref)
  }
})

test('keyboard only: the context-menu key opens the menu, arrows and Enter move a note, focus returns', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-keys`
  const [note] = await seed(request, root, 1, 'keys')
  const other = await apiCreateNote(request, {
    title: prefixedTitle('keys other'),
    path: `${root}/zzz/o.md`,
  })
  try {
    await page.goto('/')
    await noteRow(page, note.ref).focus()
    await page.keyboard.press('Shift+F10')

    const menu = page.getByRole('menu')
    await expect(menu).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: 'Move to…' })).toBeFocused()
    await page.keyboard.press('ArrowDown')
    await expect(menu.getByRole('menuitem', { name: 'Rename' })).toBeFocused()
    await page.keyboard.press('ArrowDown') // wraps
    await expect(menu.getByRole('menuitem', { name: 'Move to…' })).toBeFocused()
    await page.keyboard.press('End')
    await expect(menu.getByRole('menuitem', { name: 'Rename' })).toBeFocused()
    await page.keyboard.press('Home')

    // Escape closes and returns focus to the row.
    await page.keyboard.press('Escape')
    await expect(menu).toHaveCount(0)
    await expect(noteRow(page, note.ref)).toBeFocused()

    await page.keyboard.press('Shift+F10')
    await page.keyboard.press('Enter') // Move to...
    await page.getByRole('menuitem', { name: `${root}/zzz`, exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('tree-toast')).toContainText('Moved')
    await expect(noteRow(page, note.ref)).toBeFocused()
    expect((await listPaths(page))[note.ref]).toBe(`${root}/zzz/keys-1.md`)

    // Outside click closes the menu.
    await page.keyboard.press('Shift+F10')
    await expect(page.getByRole('menu')).toBeVisible()
    await page.locator('.empty, .live').first().click({ force: true }).catch(() => {})
    await page.mouse.click(1000, 600)
    await expect(page.getByRole('menu')).toHaveCount(0)
  } finally {
    await apiDeleteNote(request, note.ref)
    await apiDeleteNote(request, other.ref)
  }
})

test('search keeps the flat list, and its rows still have the note menu', async ({
  authedPage: page,
  request,
}) => {
  const root = `${runId()}-search`
  const title = prefixedTitle('zebrafindable')
  const note = await apiCreateNote(request, { title, path: `${root}/z.md` })
  try {
    await page.goto('/')
    await page.getByTestId('search-input').fill('zebrafindable')
    await page.getByTestId('search-input').press('Enter')
    await expect(page.getByTestId('note-list')).toBeVisible()
    await page.locator(`li:has(> a[data-id="${note.ref}"]) > .more`).click({ force: true })
    await expect(page.getByRole('menuitem')).toHaveText(['Move to…', 'Rename'])
    await expect(page.getByTestId('new-folder-button')).toBeDisabled()
  } finally {
    await apiDeleteNote(request, note.ref)
  }
})
