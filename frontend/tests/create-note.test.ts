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

function stubNetwork(afterCreate: Note[]): void {
  posted = null
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/notes' && method === 'GET') {
      return json({ notes: posted === null ? [EXISTING] : afterCreate })
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

async function createNoteThroughUI(title: string): Promise<void> {
  host.querySelector<HTMLButtonElement>('[data-testid="new-note-button"]')!.click()
  flushSync()
  const input = host.querySelector<HTMLInputElement>('[data-testid="create-title-input"]')!
  input.value = title
  input.dispatchEvent(new Event('input'))
  host
    .querySelector('[data-testid="create-form"]')!
    .dispatchEvent(new Event('submit', { cancelable: true }))
  flushSync()
}

describe('creating a note from the browser (KAN-1040)', () => {
  it('posts the trimmed title and lands in the editor on the new note', async () => {
    renderApp()
    await ready()

    await createNoteThroughUI('  A fresh note  ')
    await vi.waitFor(() => {
      flushSync()
      expect(globalThis.location.pathname).toBe(`/notes/${CREATED.ref}`)
    })

    expect(posted).toEqual({ url: '/api/v1/notes', body: { title: 'A fresh note' } })
    await editorArrived(host)
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('[data-testid="credential-state"]')).not.toBeNull()
    })
    expect(host.querySelector<HTMLInputElement>('[data-testid="title-input"]')?.value).toBe(CREATED.title)
  })

  it('adds the new note to the sidebar list', async () => {
    renderApp()
    await ready()

    await createNoteThroughUI('A fresh note')
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector(`a[href="/notes/${CREATED.ref}"]`)).not.toBeNull()
    })
  })

  it('surfaces a failure the same way a fetch failure would, and does not navigate', async () => {
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

    await createNoteThroughUI('Doomed note')
    await vi.waitFor(() => {
      flushSync()
      expect(host.textContent).toContain('Title is required.')
    })
    expect(globalThis.location.pathname).toBe('/')
  })
})
