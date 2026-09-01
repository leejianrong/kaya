// @vitest-environment jsdom
/**
 * KAN-1043, end to end: open a real note, edit the path field, blur, and watch the sidebar's tree
 * re-group it into the new folder — the wiring `tests/editor-pane.test.ts` cannot see, since it
 * never mounts `App` or a real sidebar. Same mocked-network harness as
 * `tests/unsaved-navigation.test.ts` and `tests/create-note.test.ts`.
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

const MOVED: Note = {
  ...ORIGINAL,
  path: 'archive/weekly-review.md',
  updated_at: '2026-09-01T09:00:00.000000+00:00',
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch
let moved = false
let patched: Record<string, unknown> | null = null

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubNetwork(): void {
  moved = false
  patched = null
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/notes' && method === 'GET') {
      return json({ notes: [moved ? MOVED : ORIGINAL] })
    }
    if (url === `/api/v1/notes/${ORIGINAL.ref}` && method === 'PATCH') {
      patched = JSON.parse(String(init?.body))
      moved = true
      return json(MOVED)
    }
    if (url === `/api/v1/notes/${ORIGINAL.ref}`) {
      return json(moved ? MOVED : ORIGINAL)
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

function pathInput(): HTMLInputElement {
  return host.querySelector<HTMLInputElement>('[data-testid="path-input"]')!
}

function folderNames(): string[] {
  return Array.from(host.querySelectorAll<HTMLElement>('button.folder .title')).map(
    (span) => span.textContent!,
  )
}

describe("moving a note's folder from the browser (KAN-1043)", () => {
  it("re-groups the sidebar tree into the new folder once the blur PATCH resolves", async () => {
    renderApp()
    await ready()
    expect(folderNames()).toContain('journal')
    expect(folderNames()).not.toContain('archive')

    pathInput().value = 'archive/weekly-review.md'
    pathInput().dispatchEvent(new Event('input'))
    pathInput().dispatchEvent(new Event('blur'))

    await vi.waitFor(() => {
      flushSync()
      expect(folderNames()).toContain('archive')
    })
    expect(folderNames()).not.toContain('journal')
    expect(patched).toEqual({ path: 'archive/weekly-review.md' })
    expect(patched).not.toHaveProperty('if_updated_at')
  })

  it('sends no request when the path is blurred unchanged', async () => {
    renderApp()
    await ready()

    pathInput().dispatchEvent(new Event('blur'))
    flushSync()

    expect(patched).toBeNull()
  })
})
