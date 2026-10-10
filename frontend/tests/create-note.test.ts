// @vitest-environment jsdom
/**
 * KAN-1040, end to end: click "+ New note" in the real sidebar, type a title, submit, and land in
 * the editor on the fresh note — the wiring `tests/sidebar.test.ts` cannot see, since it never
 * mounts `App` or a real `createNote()` call. Same mocked-network harness as
 * `tests/unsaved-navigation.test.ts`.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { FAKE_TOKEN } from './token'

const EXISTING: Note = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/2026/08/weekly-review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
  team_id: null,
}

const CREATED: Note = {
  ref: 'NOTE-99',
  id: 99,
  title: 'A fresh note',
  body: '',
  path: '',
  created_at: '2026-09-01T10:00:00+00:00',
  updated_at: '2026-09-01T10:00:00.000000+00:00',
  team_id: null,
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch
let posted: { url: string; body: unknown } | null = null

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubNetwork(afterCreate: Note[], before: Note[] = [EXISTING]): void {
  posted = null
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/notes' && method === 'GET') {
      return json({ notes: posted === null ? before : afterCreate })
    }
    if (url === '/api/v1/notes' && method === 'POST') {
      posted = { url, body: JSON.parse(String(init?.body)) }
      return json(CREATED, 201)
    }
    if (url === `/api/v1/notes/${EXISTING.ref}`) {
      return json(EXISTING)
    }
    if (url === `/api/v1/notes/${EXISTING.ref}/backlinks`) {
      return json({ notes: [] })
    }
    if (url === `/api/v1/notes/${CREATED.ref}`) {
      return json(CREATED)
    }
    if (url === `/api/v1/notes/${CREATED.ref}/backlinks`) {
      return json({ notes: [] })
    }
    return json({ error: { code: 'not_found', message: `nothing fake at ${url}` } }, 404)
  }) as unknown as typeof fetch
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  stubNetwork([EXISTING, CREATED])
  globalThis.history.pushState({}, '', '/')
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  auth.clearToken()
  globalThis.fetch = realFetch
  globalThis.history.pushState({}, '', '/')
  vi.restoreAllMocks()
})

function renderApp(): void {
  mounted.push(mount(App, { target: host, props: {} }))
  flushSync()
}

async function ready(): Promise<void> {
  await vi.waitFor(() => {
    flushSync()
    expect(host.querySelector('[data-testid="note-tree"]')).not.toBeNull()
  })
}

function createNoteThroughUI(): void {
  host.querySelector<HTMLButtonElement>('[data-testid="new-note-button"]')!.click()
  flushSync()
}

describe('creating a note from the browser (KAY-166)', () => {
  it('posts Untitled at once, with a path, and lands in the editor on the new note', async () => {
    renderApp()
    await ready()

    createNoteThroughUI()
    await vi.waitFor(() => {
      flushSync()
      expect(globalThis.location.pathname).toBe(`/notes/${CREATED.ref}`)
    })

    // EXISTING lives in journal/2026/08, but no note is open yet and no folder was clicked.
    expect(posted).toEqual({ url: '/api/v1/notes', body: { title: 'Untitled', path: 'untitled.md' } })
    await editorArrived(host)
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('.brand')).not.toBeNull()
    })
    expect(host.querySelector<HTMLInputElement>('[data-testid="title-input"]')?.value).toBe(CREATED.title)
  })

  it('focuses and selects the title field so typing names the note', async () => {
    renderApp()
    await ready()

    createNoteThroughUI()
    await vi.waitFor(() => {
      flushSync()
      const input = host.querySelector<HTMLInputElement>('[data-testid="title-input"]')
      expect(input).not.toBeNull()
      expect(document.activeElement).toBe(input)
      expect(input!.selectionStart).toBe(0)
      expect(input!.selectionEnd).toBe(input!.value.length)
    })
  })

  it('puts the note in the open note\'s folder, and counts past a taken Untitled', async () => {
    const taken: Note = { ...EXISTING, ref: 'NOTE-7', id: 7, title: 'Untitled', path: 'journal/2026/08/untitled.md' }
    stubNetwork([EXISTING, taken, CREATED], [EXISTING, taken])
    globalThis.history.pushState({}, '', `/notes/${EXISTING.ref}`)
    renderApp()
    await ready()
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector(`a[href="/notes/${taken.ref}"]`)).not.toBeNull()
    })

    createNoteThroughUI()
    await vi.waitFor(() => {
      expect(posted).toEqual({
        url: '/api/v1/notes',
        body: { title: 'Untitled 1', path: 'journal/2026/08/untitled-1.md' },
      })
    })
  })

  it('adds the new note to the sidebar list', async () => {
    renderApp()
    await ready()

    createNoteThroughUI()
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector(`a[href="/notes/${CREATED.ref}"]`)).not.toBeNull()
    })
  })

  it('surfaces a failure the same way a fetch failure would, with no phantom row and no navigation', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/notes' && method === 'GET') {
        return json({ notes: [EXISTING] })
      }
      if (url === '/api/v1/notes' && method === 'POST') {
        return json({ error: { code: 'validation_error', message: 'Title is required.' } }, 422)
      }
      if (url === `/api/v1/notes/${EXISTING.ref}`) {
        return json(EXISTING)
      }
      if (url === `/api/v1/notes/${EXISTING.ref}/backlinks`) {
        return json({ notes: [] })
      }
      return json({ error: { code: 'not_found', message: `nothing fake at ${url}` } }, 404)
    }) as unknown as typeof fetch

    renderApp()
    await ready()

    createNoteThroughUI()
    await vi.waitFor(() => {
      flushSync()
      expect(host.textContent).toContain('Title is required.')
    })
    expect(globalThis.location.pathname).toBe('/')
    expect(host.querySelector(`a[href="/notes/${CREATED.ref}"]`)).toBeNull()
  })
})
