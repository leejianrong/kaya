// @vitest-environment jsdom
/**
 * KAN-1042, end to end: open a real note, edit the title field, blur, and watch the sidebar's row
 * label update — the wiring `tests/editor-pane.test.ts` cannot see, since it never mounts `App` or a
 * real sidebar. Same mocked-network harness as `tests/unsaved-navigation.test.ts` and
 * `tests/create-note.test.ts`.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { FAKE_TOKEN } from './token'

const ORIGINAL: Note = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/2026/08/weekly-review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
}

const RENAMED: Note = { ...ORIGINAL, title: 'Weekly review (renamed)', updated_at: '2026-09-01T09:00:00.000000+00:00' }

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch
let renamed = false
let patched: Record<string, unknown> | null = null

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubNetwork(): void {
  renamed = false
  patched = null
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/notes' && method === 'GET') {
      return json({ notes: [renamed ? RENAMED : ORIGINAL] })
    }
    if (url === `/api/v1/notes/${ORIGINAL.ref}` && method === 'PATCH') {
      patched = JSON.parse(String(init?.body))
      renamed = true
      return json(RENAMED)
    }
    if (url === `/api/v1/notes/${ORIGINAL.ref}`) {
      return json(renamed ? RENAMED : ORIGINAL)
    }
    if (url === `/api/v1/notes/${ORIGINAL.ref}/backlinks`) {
      return json({ notes: [] })
    }
    if (url === `/api/v1/notes/${ORIGINAL.ref}/links`) {
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
  globalThis.history.pushState({}, '', `/notes/${ORIGINAL.ref}`)
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

function titleInput(): HTMLInputElement {
  return host.querySelector<HTMLInputElement>('[data-testid="title-input"]')!
}

describe('retitling a note from the browser (KAN-1042)', () => {
  it('updates the sidebar row label once the blur PATCH resolves', async () => {
    renderApp()
    await ready()
    expect(host.querySelector(`a[href="/notes/${ORIGINAL.ref}"]`)!.textContent).toContain(
      'Weekly review',
    )

    titleInput().value = 'Weekly review (renamed)'
    titleInput().dispatchEvent(new Event('input'))
    titleInput().dispatchEvent(new Event('blur'))

    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector(`a[href="/notes/${ORIGINAL.ref}"]`)!.textContent).toContain(
        'renamed',
      )
    })
    expect(patched).toEqual({ title: 'Weekly review (renamed)' })
    // Title-only writes are unguarded by design (ADR 0009) — no if_updated_at anywhere in the body.
    expect(patched).not.toHaveProperty('if_updated_at')
  })

  it('sends no request when the title is blurred unchanged', async () => {
    renderApp()
    await ready()

    titleInput().dispatchEvent(new Event('blur'))
    flushSync()

    expect(patched).toBeNull()
  })
})
