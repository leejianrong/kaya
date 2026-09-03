// @vitest-environment jsdom
/**
 * Where KAN-568's rail *is*, which is the half of that card `tests/backlinks-panel.test.ts` cannot
 * see: mounting the panel on its own proves everything about the panel and nothing about the shell
 * it was put into.
 *
 * Three claims, and each is a decision `App.svelte` argues rather than an accident of layout:
 *
 * - the rail is a **fourth region**, a sibling of `main` — so nothing that happens to the document's
 *   panes can reach it;
 * - it is on screen **exactly when a note route is**, so there is no empty stripe on `/` and no
 *   overlapping column when the grid says there is a rail and the template says there is not;
 * - **the preview toggle cannot touch it.** That is the one with a history: KAN-554 kept `EditorPane`
 *   outside the toggle's `{#if}` because a command about one pane must not discard another's state,
 *   KAN-962 restated it, and a rail placed inside `.split` would be one edit away from inheriting the
 *   problem. Outside `main` the toggle cannot reach it *at all*, and this file is where "cannot" is
 *   the word rather than "does not".
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
  team_id: null,
}

const LINKING: Note = { ...NOTE, ref: 'NOTE-2', id: 2, title: 'Points at the weekly review' }

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const body =
      url === '/api/v1/notes'
        ? { notes: [NOTE, LINKING] }
        : url === `/api/v1/notes/${NOTE.ref}`
          ? NOTE
          : url === `/api/v1/notes/${NOTE.ref}/backlinks`
            ? { notes: [LINKING] }
            : { error: { code: 'not_found', message: `nothing fake at ${url}` } }
    return new Response(JSON.stringify(body), {
      status: 'error' in body ? 404 : 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  auth.clearToken()
  globalThis.fetch = realFetch
  globalThis.history.pushState({}, '', '/')
})

function renderApp(): void {
  mounted.push(mount(App, { target: host, props: {} }))
  flushSync()
}

/** Wait for the rail to have listed its rows. A poll, never a tick count. */
async function railListed(): Promise<HTMLElement> {
  let element: HTMLElement | null = null
  await vi.waitFor(() => {
    flushSync()
    element = host.querySelector<HTMLElement>('[data-testid="backlinks"]')
    expect(element, 'the rail never listed anything').not.toBeNull()
  })
  return element!
}

function click(testid: string): void {
  host.querySelector<HTMLButtonElement>(`[data-testid="${testid}"]`)!.click()
  flushSync()
}

describe('the rail is a region of the shell, beside the document rather than inside it', () => {
  beforeEach(() => globalThis.history.pushState({}, '', `/notes/${NOTE.ref}`))

  it('lists what links to the open note, from the shell’s own wiring', async () => {
    renderApp()
    const listed = await railListed()

    // The positive control for every "is not inside" assertion below: without it they would all be
    // satisfied by a rail that rendered nothing at all.
    expect(listed.textContent).toContain('Points at the weekly review')
    expect(host.querySelector('a[href="/notes/NOTE-2"]')).not.toBeNull()
  })

  it('sits outside `main`, outside `.split`, and outside S9’s container', async () => {
    renderApp()
    await railListed()
    const rail = host.querySelector<HTMLElement>('aside.rail')!

    // Three closests rather than one, because each names a different thing that could reach it: a
    // route branch (`main`), the preview toggle (`.split`), and PLAN §S9's rule (`.editor-host`).
    expect(rail.closest('main')).toBeNull()
    expect(rail.closest('.split')).toBeNull()
    expect(rail.closest('.editor-host')).toBeNull()
    // And it really is inside the grid's rail column: R13/KAN-1064 wrapped the panel in
    // `RightRail.svelte`'s tab strip, so the direct child of `.shell` carrying `grid-area: rail`
    // is `.right-rail` now — see `App.svelte`'s `.shell > :global(.right-rail)` — and `aside.rail`
    // sits one level inside that wrapper rather than touching `.shell` itself.
    const wrapper = rail.closest('.right-rail')
    expect(wrapper).not.toBeNull()
    expect(wrapper?.parentElement?.classList.contains('shell')).toBe(true)
  })

  it('does not put a node inside the editor container, which the S9 guards also cover', async () => {
    renderApp()
    await editorArrived(host)
    const container = host.querySelector('.editor-host')!

    // Over `childNodes`, not `children`: the risk S9 is guarding is a **text node**, and an
    // element-wise check cannot see one. `tests/shell.test.ts` owns the general version; this says
    // the fourth region did not smuggle one in.
    const own = new Set<Node>(container.querySelectorAll(':scope > .cm-editor'))
    expect(Array.from(container.childNodes).filter((node) => !own.has(node))).toEqual([])
  })

  it('gives the shell its rail column exactly when the rail is there', async () => {
    // The `{#if}` and the grid class are one expression in `App.svelte` on purpose: a column with no
    // rail is an empty stripe, and a rail with no column overlaps `main`. This is the assertion that
    // notices if they are ever split into two.
    renderApp()
    await railListed()

    expect(host.querySelector('.shell')!.classList.contains('railed')).toBe(true)
  })
})

describe('the preview toggle cannot reach the rail', () => {
  beforeEach(() => globalThis.history.pushState({}, '', `/notes/${NOTE.ref}`))

  it('keeps the very same element, with its rows, across a hide and a show', async () => {
    renderApp()
    await editorArrived(host)
    await railListed()
    const rail = host.querySelector<HTMLElement>('aside.rail')!
    const row = host.querySelector<HTMLElement>('a[href="/notes/NOTE-2"]')!

    click('toggle-preview')
    expect(host.querySelector('[data-testid="preview"]')).toBeNull()
    click('toggle-preview')

    // Element **identity**, not presence. A rail placed inside `.split` would be a fresh component
    // instance here — a new fetch, a flash of `Loading…`, and the panel's state discarded — and a
    // presence check would be perfectly happy about all of it.
    expect(host.querySelector('aside.rail')).toBe(rail)
    expect(host.querySelector('a[href="/notes/NOTE-2"]')).toBe(row)
  })

  it('does not make the rail ask again', async () => {
    renderApp()
    await railListed()
    const backlinkCalls = () =>
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).endsWith('/backlinks')).length

    expect(backlinkCalls()).toBe(1)
    click('toggle-preview')
    click('toggle-preview')
    await vi.waitFor(() => {
      flushSync()
      expect(backlinkCalls()).toBe(1)
    })
  })
})

describe('the rail is absent where it would have nothing to say', () => {
  it('is not rendered on the note list', async () => {
    globalThis.history.pushState({}, '', '/')
    renderApp()
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('nav.sidebar')).not.toBeNull()
    })

    // Both halves: no rail, and no grid column reserved for one. A fourth region standing empty
    // beside the note list reads as a broken app, which is the same call `.unauthenticated` already
    // makes about the sidebar.
    expect(host.querySelector('aside.rail')).toBeNull()
    expect(host.querySelector('.shell')!.classList.contains('railed')).toBe(false)
    expect(
      vi.mocked(globalThis.fetch).mock.calls.filter(([input]) => String(input).endsWith('/backlinks')),
    ).toEqual([])
  })

  it('is not rendered on an unknown path', async () => {
    globalThis.history.pushState({}, '', '/nowhere/at/all')
    renderApp()
    flushSync()

    expect(host.querySelector('aside.rail')).toBeNull()
    expect(host.querySelector('.shell')!.classList.contains('railed')).toBe(false)
  })

  it('is not rendered without a credential', async () => {
    // The landing state replaces the whole of `main`; a rail beside a sign-in page would be a
    // request the app cannot make and a heading about a note nobody has opened.
    auth.clearToken()
    globalThis.history.pushState({}, '', `/notes/${NOTE.ref}`)
    renderApp()
    flushSync()

    expect(host.querySelector('[data-testid="paste-form"]')).not.toBeNull()
    expect(host.querySelector('aside.rail')).toBeNull()
    expect(host.querySelector('.shell')!.classList.contains('railed')).toBe(false)
  })
})

describe('a 401 from the rail reaches the shell’s credential lifecycle', () => {
  it('returns the app to the landing state rather than being absorbed by the panel', async () => {
    // The rail is the only region that could plausibly swallow one, because it is the only region
    // whose failure has a local rendering. `App.svelte` owns `discard()`; the panel hands the
    // refusal over and shows nothing itself.
    globalThis.history.pushState({}, '', `/notes/${NOTE.ref}`)
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/backlinks')) {
        return new Response(
          JSON.stringify({ error: { code: 'invalid_token', message: 'That token is not valid.' } }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        )
      }
      const body = url === '/api/v1/notes' ? { notes: [NOTE] } : NOTE
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as unknown as typeof fetch

    renderApp()
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('[data-testid="paste-form"]')).not.toBeNull()
    })

    expect(host.querySelector('aside.rail')).toBeNull()
    expect(host.querySelector('[data-testid="credential-state"]')!.textContent).toBe('token not set')
    // The API's own words, on the landing state, and never a fragment of the credential.
    expect(host.textContent).toContain('That token is not valid.')
    for (let start = 0; start + 4 <= FAKE_TOKEN.length; start += 1) {
      expect(document.body.innerHTML).not.toContain(FAKE_TOKEN.slice(start, start + 4))
    }
  })
})
