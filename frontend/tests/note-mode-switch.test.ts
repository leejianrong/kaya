// @vitest-environment jsdom
/**
 * KAN-1819: the Read | Edit | Split switch, mounted in the real shell. jsdom has no layout, so this
 * proves what is *rendered* and *kept* — which segments exist per size class, what a note opens in,
 * what is remembered, that Save and Delete follow the mode, and above all that **no switch ever
 * remounts the editor**. `e2e/note-mode.spec.ts` measures the layout in a real browser.
 */

import { EditorView } from '@codemirror/view'
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import * as auth from '../src/lib/auth'
import { modeStorageKey } from '../src/lib/noteMode'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { previewRendered } from './preview-arrival'
import { FAKE_TOKEN } from './token'

const NOTE: Note = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
  team_id: null,
}

const CREATED: Note = { ...NOTE, ref: 'NOTE-99', id: 99, title: 'A fresh note', body: '', path: '' }

let host: HTMLDivElement
let instance: unknown
const realFetch = globalThis.fetch

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A `matchMedia` whose width can change under a mounted app, firing the `change` listeners. */
let setWidth: (width: number) => void

function stubViewport(initial: number): void {
  let width = initial
  const listeners = new Set<() => void>()
  vi.stubGlobal('matchMedia', (query: string) => {
    // Anything that is not one of the window-class queries (CM6 asks about colour schemes) is "no".
    const min = Number(/min-width: (\d+)px/.exec(query)?.[1] ?? Number.POSITIVE_INFINITY)
    return {
      get matches() {
        return width >= min
      },
      // Only the window-class queries get a live `change`; CM6's own (print, colour scheme) do not.
      addEventListener: (_type: string, fn: () => void) => {
        if (Number.isFinite(min)) {
          listeners.add(fn)
        }
      },
      removeEventListener: (_type: string, fn: () => void) => listeners.delete(fn),
    }
  })
  setWidth = (next) => {
    width = next
    for (const fn of listeners) {
      fn()
    }
    flushSync()
  }
}

async function open(path: string, width: number, awaitEditor = true): Promise<void> {
  stubViewport(width)
  globalThis.history.pushState({}, '', path)
  auth.setToken(FAKE_TOKEN)
  instance = mount(App, { target: host, props: {} })
  flushSync()
  if (awaitEditor) {
    await editorArrived(host)
  }
}

const q = (testid: string): HTMLElement | null =>
  host.querySelector<HTMLElement>(`[data-testid="${testid}"]`)

function click(testid: string): void {
  q(testid)!.click()
  flushSync()
}

const dataMode = (): string | null => host.querySelector('.split')?.getAttribute('data-mode') ?? null
const pressed = (testid: string): string | null => q(testid)?.getAttribute('aria-pressed') ?? null

function view(): EditorView {
  return EditorView.findFromDOM(host.querySelector<HTMLElement>('.cm-editor')!)!
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/notes' && method === 'GET') {
      return json(200, { notes: [NOTE] })
    }
    if (url === '/api/v1/notes' && method === 'POST') {
      return json(201, CREATED)
    }
    if (url === `/api/v1/notes/${NOTE.ref}`) {
      return json(200, NOTE)
    }
    if (url === `/api/v1/notes/${CREATED.ref}`) {
      return json(200, CREATED)
    }
    if (url.includes('/preferences')) {
      return json(200, { format_on_save: false })
    }
    if (url.startsWith('/api/v1/notes/')) {
      return json(200, { backlinks: [], versions: [], links: [], notes: [] })
    }
    return json(404, { error: { code: 'not_found', message: `nothing fake at ${url}` } })
  }) as unknown as typeof fetch
})

afterEach(() => {
  unmount(instance as never)
  host.remove()
  auth.clearToken()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
  globalThis.fetch = realFetch
  globalThis.history.pushState({}, '', '/')
})

describe('expanded', () => {
  it('opens in Edit with all three segments, Edit pressed, and no preview mounted', async () => {
    await open('/notes/NOTE-6', 1440)

    expect(dataMode()).toBe('edit')
    expect(pressed('mode-read')).toBe('false')
    expect(pressed('mode-edit')).toBe('true')
    expect(pressed('mode-split')).toBe('false')
    expect(q('preview')).toBeNull()
    expect(q('toggle-preview')).toBeNull()
  })

  it('keeps one editor view across Read, Split and back, and Read shows unsaved text', async () => {
    await open('/notes/NOTE-6', 1440)
    const first = view()
    const element = host.querySelector('.cm-editor')
    first.dispatch({ changes: { from: 0, to: first.state.doc.length, insert: '# Unsaved heading' } })
    flushSync()

    click('mode-read')
    await previewRendered(host)
    expect(dataMode()).toBe('read')
    // The editor is still mounted (hidden by CSS), and the preview follows what it holds.
    expect(host.querySelector('.pane.reading .editor-host .cm-editor')).toBe(element)
    expect(q('preview')!.querySelector('h1')?.textContent).toBe('Unsaved heading')

    click('mode-split')
    expect(dataMode()).toBe('split')
    expect(q('preview')).not.toBeNull()
    click('mode-edit')
    expect(q('preview')).toBeNull()

    expect(host.querySelector('.cm-editor')).toBe(element)
    expect(view()).toBe(first)
    expect(first.state.doc.toString()).toBe('# Unsaved heading')
  })

  it('remembers the choice for the class, and restores it on the next open', async () => {
    await open('/notes/NOTE-6', 1440)
    click('mode-read')
    expect(localStorage.getItem(modeStorageKey('expanded'))).toBe('read')
    expect(localStorage.getItem(modeStorageKey('compact'))).toBeNull()
    unmount(instance as never)
    host.replaceChildren()

    await open('/notes/NOTE-6', 1440)
    expect(dataMode()).toBe('read')
  })

  it('renders correctly when storage throws', async () => {
    // Only `localStorage`: the credential lives in `sessionStorage` and must keep working.
    vi.stubGlobal('localStorage', {
      getItem() {
        throw new Error('blocked')
      },
      setItem() {
        throw new Error('blocked')
      },
    })
    await open('/notes/NOTE-6', 1440)
    expect(dataMode()).toBe('edit')
    click('mode-read')
    expect(dataMode()).toBe('read')
  })

  it('falls back to Edit, same editor, when the viewport shrinks past Split', async () => {
    await open('/notes/NOTE-6', 1440)
    const element = host.querySelector('.cm-editor')
    click('mode-split')
    expect(dataMode()).toBe('split')

    setWidth(700)
    expect(dataMode()).toBe('edit')
    expect(q('mode-split')).toBeNull()
    expect(host.querySelector('.cm-editor')).toBe(element)
  })

  it('has no Read-only Save or Delete problem: Edit shows both', async () => {
    await open('/notes/NOTE-6', 1440)
    expect(q('delete-button')).not.toBeNull()
    expect(host.querySelector('.bar button')).not.toBeNull()
  })
})

describe('compact', () => {
  it('opens a saved note in Read, without Split, Save or Delete', async () => {
    await open('/notes/NOTE-6', 390)

    expect(dataMode()).toBe('read')
    expect(pressed('mode-read')).toBe('true')
    expect(q('mode-split')).toBeNull()
    expect(q('delete-button')).toBeNull()
    expect(host.querySelector('.bar')).toBeNull()
    // Heading and metadata remain: the title input and the ref.
    expect(q('title-input')).not.toBeNull()
    expect(host.querySelector('.meta code')?.textContent).toBe('NOTE-6')
  })

  it('shows Save and Delete in Edit, and remembers Edit for compact only', async () => {
    await open('/notes/NOTE-6', 390)
    click('mode-edit')

    expect(dataMode()).toBe('edit')
    expect(host.querySelector('.bar button')?.textContent?.trim()).toBe('Save')
    expect(q('delete-button')).not.toBeNull()
    expect(q('preview')).toBeNull()
    expect(localStorage.getItem(modeStorageKey('compact'))).toBe('edit')
    expect(localStorage.getItem(modeStorageKey('medium'))).toBeNull()
  })

  it('has no Save in Read, but never hides unsaved text in silence (KAN-1826)', async () => {
    await open('/notes/NOTE-6', 390)
    click('mode-edit')
    const v = view()
    v.dispatch({ changes: { from: 0, insert: 'x' } })
    flushSync()
    click('mode-read')

    expect(dataMode()).toBe('read')
    expect(host.querySelector('.bar')).toBeNull()
    expect(host.querySelector('.bar button')).toBeNull()
    expect(q('read-unsaved')?.textContent).toContain('Switch to Edit to save')
    expect(q('delete-button')).toBeNull()

    click('mode-edit')
    expect(q('read-unsaved')).toBeNull()
    expect(host.querySelector('.bar button')?.textContent?.trim()).toBe('Save')
  })

  it('treats medium as its own class: a compact choice does not leak into it', async () => {
    localStorage.setItem(modeStorageKey('compact'), 'edit')
    await open('/notes/NOTE-6', 700)

    expect(dataMode()).toBe('read')
    expect(q('mode-split')).toBeNull()
  })

  it('clamps a hand-edited stored value to the default', async () => {
    localStorage.setItem(modeStorageKey('compact'), 'sideways')
    await open('/notes/NOTE-6', 390)
    expect(dataMode()).toBe('read')
  })

  it('opens a note just created through New note in Edit, whatever was remembered', async () => {
    localStorage.setItem(modeStorageKey('compact'), 'read')
    await open('/', 390, false)
    await vi.waitFor(() => {
      flushSync()
      expect(q('new-note-button')).not.toBeNull()
    })

    click('new-note-button')
    const input = q('create-title-input') as HTMLInputElement
    input.value = 'A fresh note'
    input.dispatchEvent(new Event('input'))
    q('create-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    flushSync()
    await vi.waitFor(() => {
      flushSync()
      expect(globalThis.location.pathname).toBe(`/notes/${CREATED.ref}`)
      expect(dataMode()).toBe('edit')
    })
    expect(pressed('mode-edit')).toBe('true')
    // Not a choice the person made, so Read stays what is remembered.
    expect(localStorage.getItem(modeStorageKey('compact'))).toBe('read')
  })
})

describe('the control itself', () => {
  it('is a labelled group of real buttons', async () => {
    await open('/notes/NOTE-6', 1440)
    const group = q('mode-switch')!
    expect(group.getAttribute('role')).toBe('group')
    expect(group.getAttribute('aria-label')).toBe('View mode')
    const buttons = [...group.querySelectorAll('button')]
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(['Read', 'Edit', 'Split'])
    expect(buttons.every((b) => b.type === 'button' && !b.disabled)).toBe(true)
  })

  it('is absent on routes that are not a note', async () => {
    await open('/', 1440)
    expect(q('mode-switch')).toBeNull()
  })
})
