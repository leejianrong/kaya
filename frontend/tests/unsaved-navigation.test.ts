// @vitest-environment jsdom
/**
 * KAN-969, end to end: mount the real shell, type in the real editor, click a real link, and watch
 * what happens to the text.
 *
 * `tests/navigation-guard.test.ts` proves the choke point in `lib/router.ts` in isolation, with a
 * stub guard; `tests/editor-pane.test.ts`'s new block proves `EditorPane` publishes `dirty` and
 * answers `beforeunload` correctly. Neither proves the three pieces are actually wired together — that
 * `App.svelte` registers a guard that reads the *real* `dirty`, that the guard is consulted by a
 * *real* click on each of the three surfaces the card names, or that declining the dialog leaves the
 * typed text exactly where it was. This file is where that wiring is checked, against a mounted `App`
 * with mocked network calls, the same harness `tests/backlinks-rail.test.ts` established.
 *
 * `window.confirm` is stubbed per test rather than left to jsdom's own stand-in, which always answers
 * `undefined` (`Not implemented`) — `App.svelte`'s `confirmNavigation` treats that as "allow", so an
 * un-stubbed run here would never exercise the refusal path at all and would look green regardless.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { FAKE_TOKEN } from './token'

const NOTE: Note = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/2026/08/weekly-review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
}

const OTHER: Note = {
  ...NOTE,
  ref: 'NOTE-7',
  id: 7,
  title: 'Architecture notes',
  body: '# Architecture\n',
  path: 'architecture.md',
}

const LINKING: Note = {
  ...NOTE,
  ref: 'NOTE-2',
  id: 2,
  title: 'Points at the weekly review',
  body: '[[Weekly review]]',
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

function stubNetwork(): void {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/v1/notes') {
      return json({ notes: [NOTE, OTHER, LINKING] })
    }
    if (url === `/api/v1/notes/${NOTE.ref}`) {
      return json(NOTE)
    }
    if (url === `/api/v1/notes/${OTHER.ref}`) {
      return json(OTHER)
    }
    if (url === `/api/v1/notes/${NOTE.ref}/backlinks`) {
      return json({ notes: [LINKING] })
    }
    if (url === `/api/v1/notes/${OTHER.ref}/backlinks`) {
      return json({ notes: [] })
    }
    return json({ error: { code: 'not_found', message: `nothing fake at ${url}` } }, 404)
  }) as unknown as typeof fetch
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  stubNetwork()
  globalThis.history.pushState({}, '', `/notes/${NOTE.ref}`)
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

/** The live `EditorView`'s document, read the way a person would look at the screen. */
function documentText(): string {
  return host.querySelector('.cm-content')!.textContent!
}

/** A keystroke, dispatched straight at CM6 the way `editor-pane.test.ts` does. */
async function typeIntoOpenEditor(text: string): Promise<void> {
  await editorArrived(host)
  const { EditorView } = await import('@codemirror/view')
  const view = EditorView.findFromDOM(host.querySelector('.cm-editor')!)!
  view.dispatch({ changes: { from: view.state.doc.length, insert: text }, userEvent: 'input.type' })
  flushSync()
}

function click(href: string): void {
  host.querySelector<HTMLAnchorElement>(`a[href="${href}"]`)!.click()
  flushSync()
}

async function ready(): Promise<void> {
  // The sidebar's default view is the folder tree, not the flat list — `note-tree`, not `note-list`.
  await vi.waitFor(() => {
    flushSync()
    expect(host.querySelector('[data-testid="note-tree"]')).not.toBeNull()
  })
}

describe('a click on a note stays put when the editor is dirty and the answer is no', () => {
  it('refuses through the sidebar’s flat list', async () => {
    renderApp()
    await ready()
    await typeIntoOpenEditor('MARKER-TEXT')
    const confirm = vi.spyOn(globalThis, 'confirm').mockReturnValue(false)

    click(`/notes/${OTHER.ref}`)

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(confirm.mock.calls[0][0]).toMatch(/unsaved/i)
    expect(globalThis.location.pathname).toBe(`/notes/${NOTE.ref}`)
    expect(documentText()).toContain('MARKER-TEXT')
  })

  it('refuses through the backlinks rail', async () => {
    renderApp()
    await ready()
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('[data-testid="backlinks"]')).not.toBeNull()
    })
    await typeIntoOpenEditor('MARKER-TEXT')
    vi.spyOn(globalThis, 'confirm').mockReturnValue(false)

    click(`/notes/${LINKING.ref}`)

    expect(globalThis.location.pathname).toBe(`/notes/${NOTE.ref}`)
    expect(documentText()).toContain('MARKER-TEXT')
  })

  it('refuses through the topbar’s own link home', async () => {
    renderApp()
    await ready()
    await typeIntoOpenEditor('MARKER-TEXT')
    vi.spyOn(globalThis, 'confirm').mockReturnValue(false)

    click('/')

    expect(globalThis.location.pathname).toBe(`/notes/${NOTE.ref}`)
    expect(documentText()).toContain('MARKER-TEXT')
  })
})

describe('a click on a note proceeds when the editor is dirty and the answer is yes', () => {
  it('navigates and the next note replaces the discarded text', async () => {
    renderApp()
    await ready()
    await typeIntoOpenEditor('MARKER-TEXT')
    vi.spyOn(globalThis, 'confirm').mockReturnValue(true)

    click(`/notes/${OTHER.ref}`)

    expect(globalThis.location.pathname).toBe(`/notes/${OTHER.ref}`)
    await vi.waitFor(() => {
      flushSync()
      expect(documentText()).toContain('Architecture')
    })
    expect(documentText()).not.toContain('MARKER-TEXT')
  })
})

describe('a click on a note never asks when there is nothing unsaved', () => {
  it('navigates straight through, silently, exactly as it always has for clean content', async () => {
    renderApp()
    await ready()
    await editorArrived(host)
    const confirm = vi.spyOn(globalThis, 'confirm')

    click(`/notes/${OTHER.ref}`)

    expect(confirm).not.toHaveBeenCalled()
    expect(globalThis.location.pathname).toBe(`/notes/${OTHER.ref}`)
  })
})

describe('the guard does not outlive the shell that registered it', () => {
  it('lets a fresh App instance navigate cleanly after a previous one is unmounted', async () => {
    // `setNavigationGuard` is module-level state in `router.ts`, shared by every `App` this process
    // ever mounts (every test in this file, for a start). If the effect that registers it forgot to
    // clean up on unmount, this second instance would inherit the first's now-stale guard closure —
    // one that closes over a `editorDirty` rune belonging to a component that no longer exists.
    renderApp()
    await ready()
    await typeIntoOpenEditor('MARKER-TEXT')

    for (const instance of mounted.splice(0)) {
      unmount(instance as never)
    }
    host.remove()
    host = document.createElement('div')
    document.body.append(host)

    renderApp()
    await ready()

    const confirm = vi.spyOn(globalThis, 'confirm')
    click(`/notes/${OTHER.ref}`)

    expect(confirm).not.toHaveBeenCalled()
    expect(globalThis.location.pathname).toBe(`/notes/${OTHER.ref}`)
  })
})
