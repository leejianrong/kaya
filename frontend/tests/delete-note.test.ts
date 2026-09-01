// @vitest-environment jsdom
/**
 * KAN-1041, end to end: open a real note, click Delete twice, and land back on the home view with
 * the note gone from the sidebar. Same mocked-network harness as `tests/unsaved-navigation.test.ts`
 * and `tests/create-note.test.ts`.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { FAKE_TOKEN } from './token'

const DOOMED: Note = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/2026/08/weekly-review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
}

const OTHER: Note = {
  ...DOOMED,
  ref: 'NOTE-7',
  id: 7,
  title: 'Architecture notes',
  body: '# Architecture\n',
  path: 'architecture.md',
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch
let deleted = false

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubNetwork(): void {
  deleted = false
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/notes' && method === 'GET') {
      return json({ notes: deleted ? [OTHER] : [DOOMED, OTHER] })
    }
    if (url === `/api/v1/notes/${DOOMED.ref}` && method === 'DELETE') {
      deleted = true
      return new Response(null, { status: 204 })
    }
    if (url === `/api/v1/notes/${DOOMED.ref}`) {
      return json(DOOMED)
    }
    if (url === `/api/v1/notes/${DOOMED.ref}/backlinks`) {
      return json({ notes: [] })
    }
    if (url === `/api/v1/notes/${DOOMED.ref}/links`) {
      return json({ links: [] })
    }
    return json({ error: { code: 'not_found', message: `nothing fake at ${url}` } }, 404)
  }) as unknown as typeof fetch
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  stubNetwork()
  globalThis.history.pushState({}, '', `/notes/${DOOMED.ref}`)
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
  await editorArrived(host)
}

function deleteButton(): HTMLButtonElement {
  return host.querySelector<HTMLButtonElement>('[data-testid="delete-button"]')!
}

describe('deleting a note from the browser (KAN-1041)', () => {
  it('removes the note and lands on the home view after two clicks', async () => {
    renderApp()
    await ready()
    expect(host.querySelector(`a[href="/notes/${DOOMED.ref}"]`)).not.toBeNull()

    deleteButton().click()
    flushSync()
    deleteButton().click()

    await vi.waitFor(() => {
      flushSync()
      expect(globalThis.location.pathname).toBe('/')
    })
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector(`a[href="/notes/${DOOMED.ref}"]`)).toBeNull()
    })
    expect(host.querySelector(`a[href="/notes/${OTHER.ref}"]`)).not.toBeNull()
  })

  it('never asks about unsaved changes for the note it just deleted', async () => {
    renderApp()
    await ready()
    const { EditorView } = await import('@codemirror/view')
    const view = EditorView.findFromDOM(host.querySelector('.cm-editor')!)!
    view.dispatch({ changes: { from: view.state.doc.length, insert: 'unsaved' }, userEvent: 'input.type' })
    flushSync()
    const confirm = vi.spyOn(globalThis, 'confirm')

    deleteButton().click()
    flushSync()
    deleteButton().click()

    await vi.waitFor(() => {
      flushSync()
      expect(globalThis.location.pathname).toBe('/')
    })
    expect(confirm).not.toHaveBeenCalled()
  })

  it('a single click only arms it — the note is still there', async () => {
    renderApp()
    await ready()

    deleteButton().click()
    flushSync()

    expect(globalThis.location.pathname).toBe(`/notes/${DOOMED.ref}`)
    expect(host.querySelector(`a[href="/notes/${DOOMED.ref}"]`)).not.toBeNull()
  })
})
