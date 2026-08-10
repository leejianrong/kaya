// @vitest-environment jsdom
/**
 * The component-test harness, established here so KAN-553/554/555/556 do not each add one and
 * produce three lockfile conflicts (KAN-552).
 *
 * The harness is `jsdom` plus Svelte's own `mount`/`unmount` and `flushSync`. No component-testing
 * library: `@testing-library/svelte` would buy queries and cleanup over an API that is already three
 * functions, and `frontend/` has a standing obligation to keep its dependency list short enough that
 * each addition is a decision. If a later card wants better queries, add them then, with a reason.
 *
 * What this file proves: the harness works at all, and the two structural claims this card makes —
 * PLAN §S9's container, and the fact that the KAN-723 package list is gone.
 */

import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import App from '../src/App.svelte'
import EditorPane from '../src/components/EditorPane.svelte'
import Sidebar from '../src/components/Sidebar.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'

const FAKE_TOKEN = 'kanban_pat_9QxZ4mR7vT2LbWc8NsHdKfJgYpAeUiOn3XzVrQtE5w'

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-6',
    id: 6,
    title: 'Weekly review',
    body: '# Week of 2026-08-03\n',
    path: 'journal/2026/08/weekly-review.md',
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    ...overrides,
  }
}

let host: HTMLDivElement
const mounted: unknown[] = []

function render<Props extends Record<string, unknown>>(
  component: Component<Props, Record<string, unknown>>,
  props: Props,
): HTMLDivElement {
  mounted.push(mount(component, { target: host, props }))
  flushSync()
  return host
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  auth.clearToken()
})

describe('the component harness', () => {
  it('mounts a Svelte 5 component into a jsdom document', () => {
    const target = render(Sidebar, { notes: [note()], route: { name: 'home' }, loading: false })

    expect(target.querySelector('nav')).not.toBeNull()
    expect(target.textContent).toContain('Weekly review')
    expect(target.querySelector('a')?.getAttribute('href')).toBe('/notes/NOTE-6')
  })

  it('renders a note with an empty path without crashing', () => {
    // Two of the seeded notes have `path: ''`. `path` is mutable metadata and not identity (ADR
    // 0008), so an empty one is a legitimate note and not a broken row.
    const target = render(Sidebar, {
      notes: [note({ ref: 'NOTE-3', title: 'T', path: '' })],
      route: { name: 'note', ref: 'NOTE-3' },
      loading: false,
    })

    expect(target.textContent).toContain('T')
    expect(target.querySelector('a[aria-current="page"]')).not.toBeNull()
  })
})

describe("PLAN §S9's editor container", () => {
  it('gives CodeMirror an element whose children Svelte does not own', () => {
    const target = render(EditorPane, { note: note(), error: null })
    const container = target.querySelector('.editor-host')

    expect(container).not.toBeNull()
    // Every child in here was created imperatively by the `$effect`, which is what
    // `new EditorView({ parent })` will be in KAN-553. Svelte's client runtime marks the nodes it
    // owns with a `svelte-` scoping class, and there are none in this subtree.
    for (const child of Array.from(container!.children)) {
      expect(child.className).not.toMatch(/\bs-/)
    }
    expect(container!.textContent).toContain('KAN-553')
  })

  it('empties the container on teardown, which is where view.destroy() goes', () => {
    const instance = mount(EditorPane, { target: host, props: { note: note(), error: null } })
    flushSync()
    const container = host.querySelector('.editor-host')!
    expect(container.childElementCount).toBe(1)

    unmount(instance)
    flushSync()
    // SLICES §V3: "the editor mounts once per note and tears down cleanly on navigation".
    expect(host.querySelector('.editor-host')).toBeNull()
  })

  it('renders the note body outside the container, never inside it', () => {
    const target = render(EditorPane, { note: note({ body: 'MARKER-BODY' }), error: null })

    expect(target.textContent).toContain('MARKER-BODY')
    expect(target.querySelector('.editor-host')!.textContent).not.toContain('MARKER-BODY')
  })
})

describe('the shell', () => {
  it('says whether a credential is set, and never a fragment of one', () => {
    auth.setToken(FAKE_TOKEN)
    const target = render(App, {})

    expect(target.querySelector('[data-testid="credential-state"]')?.textContent).toBe('token set')
    for (let start = 0; start + 4 <= FAKE_TOKEN.length; start += 1) {
      expect(document.body.innerHTML).not.toContain(FAKE_TOKEN.slice(start, start + 4))
    }
  })

  it('shows the no-credential state instead of fetching', () => {
    const target = render(App, {})
    expect(target.textContent).toContain('No pandan token in this tab')
    expect(target.querySelector('nav')).toBeNull()
  })

  it('carries no hard-coded build-status table (KAN-723)', () => {
    // The page this replaced claimed `kaya-client` and `kaya-cli` do not boot, months after both
    // shipped. It was a second copy of CLAUDE.md's package table, it drifted twice inside one epic,
    // and the false claim reached the built bundle — so the list is deleted, not corrected.
    auth.setToken(FAKE_TOKEN)
    const target = render(App, {})

    expect(target.textContent).not.toContain('the kaya console script')
    expect(target.textContent).not.toContain('the shared core')
    expect(target.textContent).not.toContain('Show every package')
  })
})
