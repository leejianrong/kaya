// @vitest-environment jsdom
/**
 * KAY-168: the row menu, inline rename and new-folder placeholder in `Sidebar.svelte`, with the
 * writes stubbed as callbacks (`App` owns the real ones). No note is ever lost from the rendered tree.
 */
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Sidebar from '../src/components/Sidebar.svelte'
import type { Note } from '../src/lib/types'

function note(ref: string, path: string, title = `Title ${ref}`): Note {
  return {
    ref,
    id: Number.parseInt(ref.replace(/\D/g, ''), 10),
    title,
    body: '',
    path,
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    team_id: null,
  }
}

const NOTES: Note[] = [
  note('NOTE-1', 'journal/a.md'),
  note('NOTE-2', 'journal/b.md'),
  note('NOTE-3', 'design/c.md'),
  note('NOTE-4', 'top.md'),
]

let host: HTMLDivElement
const mounted: unknown[] = []

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
})

function render(props: Record<string, unknown> = {}) {
  const callbacks = {
    onmove: vi.fn(async () => ({ ok: true, message: 'Moved.' })),
    onrenamenote: vi.fn(async () => ({ ok: true, message: 'Renamed.' })),
    onrenamefolder: vi.fn(async () => ({ ok: true, message: 'Renamed folder.' })),
    onnewfolder: vi.fn(),
    oncreate: vi.fn(),
  }
  mounted.push(
    mount(Sidebar, {
      target: host,
      props: { notes: NOTES, route: { name: 'home' }, loading: false, ...callbacks, ...props },
    }),
  )
  flushSync()
  return callbacks
}

const flush = async (): Promise<void> => {
  await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  flushSync()
}

const rowButton = (kind: string, id: string): HTMLElement =>
  host
    .querySelector<HTMLElement>(`[data-row="${kind}"][data-id="${id}"]`)!
    .closest('li')!
    .querySelector<HTMLElement>(':scope > .more')!

describe('the row menu', () => {
  it('every note and folder row has a more button', () => {
    render()
    expect(host.querySelectorAll('.more')).toHaveLength(NOTES.length + 2) // every note, plus the two folders
  })

  it('a note menu offers Move to and Rename, and the move list omits the current folder', async () => {
    const callbacks = render()
    rowButton('note', 'NOTE-1').click()
    await flush()
    const menu = host.querySelector('[role="menu"]')!
    expect(Array.from(menu.querySelectorAll('[role="menuitem"]')).map((el) => el.textContent?.trim())).toEqual([
      'Move to…',
      'Rename',
    ])
    ;(menu.querySelector('[role="menuitem"]') as HTMLElement).click()
    await flush()
    const targets = Array.from(host.querySelectorAll('[role="menuitem"]')).map((el) => el.textContent?.trim())
    expect(targets).toEqual(['Unfiled (top level)', 'design'])

    ;(Array.from(host.querySelectorAll('[role="menuitem"]')).at(1) as HTMLElement).click()
    await flush()
    expect(callbacks.onmove).toHaveBeenCalledWith(NOTES[0], 'design')
    expect(host.querySelector('[role="menu"]')).toBeNull()
    expect(host.querySelector('[data-testid="tree-toast"]')?.textContent).toContain('Moved.')
  })

  it('a folder menu offers New note here, New subfolder and Rename folder', async () => {
    const callbacks = render()
    rowButton('folder', 'journal').click()
    await flush()
    const items = Array.from(host.querySelectorAll('[role="menuitem"]'))
    expect(items.map((el) => el.textContent?.trim())).toEqual([
      'New note here',
      'New subfolder',
      'Rename folder',
    ])
    ;(items[0] as HTMLElement).click()
    expect(callbacks.oncreate).toHaveBeenCalledWith('journal')
  })

  it('Escape closes it and Arrow keys move through it', async () => {
    render()
    rowButton('note', 'NOTE-1').click()
    await flush()
    const menu = host.querySelector('[role="menu"]') as HTMLElement
    expect(document.activeElement?.textContent?.trim()).toBe('Move to…')
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(document.activeElement?.textContent?.trim()).toBe('Rename')
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    flushSync()
    expect(host.querySelector('[role="menu"]')).toBeNull()
  })

  it('an outside pointerdown closes it', async () => {
    render()
    rowButton('note', 'NOTE-1').click()
    await flush()
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    flushSync()
    expect(host.querySelector('[role="menu"]')).toBeNull()
  })
})

describe('inline rename', () => {
  it('F2 on a note row edits in place; Enter commits the trimmed title', async () => {
    const callbacks = render()
    const row = host.querySelector<HTMLElement>('[data-row="note"][data-id="NOTE-1"]')!
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'F2', bubbles: true }))
    flushSync()
    const input = host.querySelector<HTMLInputElement>('input.rename')!
    expect(input).not.toBeNull()
    input.value = '  New title  '
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(callbacks.onrenamenote).toHaveBeenCalledWith(NOTES[0], 'New title')
  })

  it('Escape cancels without calling anything', async () => {
    const callbacks = render()
    host
      .querySelector<HTMLElement>('[data-row="note"][data-id="NOTE-1"]')!
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'F2', bubbles: true }))
    flushSync()
    const input = host.querySelector<HTMLInputElement>('input.rename')!
    input.value = 'nope'
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flush()
    expect(callbacks.onrenamenote).not.toHaveBeenCalled()
    expect(host.querySelector('input.rename')).toBeNull()
  })

  it('a folder rename with a slash is refused inline and nothing is sent', async () => {
    const callbacks = render()
    host
      .querySelector<HTMLElement>('[data-row="folder"][data-id="journal"]')!
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'F2', bubbles: true }))
    flushSync()
    const input = host.querySelector<HTMLInputElement>('input.rename')!
    input.value = 'a/b'
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(callbacks.onrenamefolder).not.toHaveBeenCalled()
    expect(host.querySelector('.edit-error')?.textContent).toContain('"/"')
  })

  it('a valid folder rename calls onrenamefolder with whole paths', async () => {
    const callbacks = render()
    host
      .querySelector<HTMLElement>('[data-row="folder"][data-id="journal"]')!
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'F2', bubbles: true }))
    flushSync()
    const input = host.querySelector<HTMLInputElement>('input.rename')!
    input.value = 'diary'
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(callbacks.onrenamefolder).toHaveBeenCalledWith('journal', 'diary')
  })
})

describe('new folder', () => {
  it('adds an editable row; Enter hands a validated path up and says it is tab-only', async () => {
    const callbacks = render({ contextFolder: 'journal' })
    host.querySelector<HTMLElement>('[data-testid="new-folder-button"]')!.click()
    await flush()
    const input = host.querySelector<HTMLInputElement>('input.rename')!
    input.value = 'drafts'
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(callbacks.onnewfolder).toHaveBeenCalledWith('journal/drafts')
    expect(host.querySelector('[data-testid="tree-toast"]')?.textContent).toContain('stays until a note')
  })

  it('refuses a duplicate sibling', async () => {
    const callbacks = render({ contextFolder: '' })
    host.querySelector<HTMLElement>('[data-testid="new-folder-button"]')!.click()
    await flush()
    const input = host.querySelector<HTMLInputElement>('input.rename')!
    input.value = 'Journal'
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(callbacks.onnewfolder).not.toHaveBeenCalled()
    expect(host.querySelector('.edit-error')?.textContent).toContain('already exists')
  })

  it('shows placeholders as empty folders with the hint, and every note is still rendered', () => {
    render({ placeholders: ['ideas'] })
    expect(host.querySelector('[data-row="folder"][data-id="ideas"]')).not.toBeNull()
    expect(host.textContent).toContain('Empty. Drag a note here, or create one.')
    expect(host.querySelectorAll('[data-row="note"]')).toHaveLength(NOTES.length)
  })
})

describe('drag', () => {
  it('note rows are draggable on a fine pointer and dropping on a folder asks for the move', async () => {
    const callbacks = render()
    const row = host.querySelector<HTMLElement>('[data-row="note"][data-id="NOTE-1"]')!
    expect(row.getAttribute('draggable')).toBe('true')
    const data = new Map<string, string>()
    const transfer = { setData: (k: string, v: string) => data.set(k, v), dropEffect: '', effectAllowed: '' }
    const fire = (el: Element, type: string): Event => {
      const event = new Event(type, { bubbles: true, cancelable: true })
      Object.defineProperty(event, 'dataTransfer', { value: transfer })
      el.dispatchEvent(event)
      return event
    }
    fire(row, 'dragstart')
    flushSync()
    const target = host.querySelector<HTMLElement>('[data-row="folder"][data-id="design"]')!
    const over = fire(target, 'dragover')
    expect(over.defaultPrevented).toBe(true)
    flushSync()
    expect(target.classList.contains('drop')).toBe(true)
    fire(target, 'drop')
    await flush()
    expect(callbacks.onmove).toHaveBeenCalledWith(NOTES[0], 'design')
  })

  it('a search renders the flat list with no drag, and New folder is disabled', () => {
    render({ query: 'journal' })
    expect(host.querySelector('[data-row="note"]')!.getAttribute('draggable')).toBe('false')
    expect(host.querySelector<HTMLButtonElement>('[data-testid="new-folder-button"]')!.disabled).toBe(true)
    expect(host.querySelectorAll('.more').length).toBe(NOTES.length)
  })
})
