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
import { box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

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

/**
 * The nodes `EditorPane`'s `$effect` creates — the *only* nodes allowed inside S9's container.
 *
 * **KAN-553 changed this one line** and nothing else in the container guard: the placeholder became
 * `new EditorView({ parent })`, so the selector became `:scope > .cm-editor`. The assertions below
 * are written against "whatever the effect made", so they held across the swap unchanged — including
 * the zero state, because CM6's own `placeholder()` extension renders "No note open." *inside* the
 * view rather than as a Svelte node beside it.
 */
const IMPERATIVE = ':scope > .cm-editor'

/** A node named for a failure message: `text "loading"`, `comment ""`, `<span>`. */
function describeNode(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return `text ${JSON.stringify(node.textContent)}`
  }
  if (node.nodeType === Node.COMMENT_NODE) {
    return `comment ${JSON.stringify(node.textContent)} (a Svelte block anchor)`
  }
  return `<${node.nodeName.toLowerCase()}> ${JSON.stringify(node.textContent)}`
}

/**
 * Everything in the container that the `$effect` did not put there.
 *
 * Over **`childNodes`**, not `children`. That distinction is the whole assertion: `children` is an
 * `HTMLCollection` of elements, so it cannot see a text node — and one word of interpolated text is
 * the single most likely way a future author breaks S9. `childNodes` also sees the comment anchor a
 * `{#if}` leaves behind even when the block renders nothing, which is a Svelte-owned node in CM6's
 * subtree that looks like an empty container to any element-wise check.
 */
function foreignNodes(container: Element): string[] {
  const own = new Set<Node>(container.querySelectorAll(IMPERATIVE))
  return Array.from(container.childNodes)
    .filter((node) => !own.has(node))
    .map(describeNode)
}

describe("PLAN §S9's editor container", () => {
  it('holds exactly the nodes its own $effect created, and nothing Svelte made', () => {
    // An **identity** check, not a property check. The earlier version of this test asked whether
    // each child element carried a Svelte scoping class, which was blind three ways over: a
    // scoping class only exists when a scoped style rule matches the element, `children` never
    // sees text, and neither sees a block anchor. Asking "is this node one the effect made?"
    // replaces all three questions with one that cannot be satisfied accidentally.
    const opened = box<Note | null>(note())
    mounted.push(
      mount(EditorPane, {
        target: host,
        props: {
          get note() {
            return opened.value
          },
          error: null,
        },
      }),
    )
    flushSync()

    const container = host.querySelector('.editor-host')!

    // Both halves are load-bearing. Without the first, an empty container would pass — and an
    // empty container means the effect never ran, which is a broken editor rather than a clean one.
    expect(container.querySelectorAll(IMPERATIVE)).toHaveLength(1)
    expect(foreignNodes(container)).toEqual([])

    // Across prop states, because a rendered check only ever sees the props it was handed, and a
    // `{#if note}` inside the container would be invisible in whichever state made it false.
    // `tests/editor-container.test.ts` closes that gap properly, over the template source.
    for (const next of [note({ ref: 'NOTE-7', title: 'Architecture notes' }), null, note()]) {
      opened.value = next
      flushSync()
      expect(container.querySelectorAll(IMPERATIVE)).toHaveLength(1)
      expect(foreignNodes(container)).toEqual([])
    }
  })

  it('tears the old contents down when the note changes, rather than stacking them up', () => {
    // SLICES §V3: "the editor mounts once per note and tears down cleanly on navigation (no leaked
    // listeners)". The `$effect`'s return value is what makes that true, and this is the assertion
    // that notices when it stops being returned — an `EditorView` per visited note, all of them
    // still listening, is a leak that looks like nothing until the app is slow.
    const opened = box<Note | null>(note())
    mounted.push(
      mount(EditorPane, {
        target: host,
        props: {
          get note() {
            return opened.value
          },
          error: null,
        },
      }),
    )
    flushSync()

    const container = host.querySelector('.editor-host')!
    expect(container.childElementCount).toBe(1)

    opened.value = note({ ref: 'NOTE-7', title: 'Architecture notes' })
    flushSync()
    expect(container.childElementCount).toBe(1)

    opened.value = null
    flushSync()
    expect(container.childElementCount).toBe(1)
    expect(container.textContent).toContain('No note open')
  })

  it('removes the container itself on unmount', () => {
    const instance = mount(EditorPane, { target: host, props: { note: note(), error: null } })
    flushSync()
    expect(host.querySelector('.editor-host')).not.toBeNull()

    unmount(instance)
    flushSync()
    expect(host.querySelector('.editor-host')).toBeNull()
  })

  /**
   * **This assertion inverted in KAN-553, and the inversion is the card landing rather than a pin
   * being edited away.**
   *
   * KAN-552 asserted the body renders *outside* the container, because the body was a
   * `<pre>` beside a placeholder and anything in the container was by definition Svelte's. Under a
   * real editor the body *is* the document, and the document lives inside CM6's subtree — so "the
   * body is never inside the container" is now precisely false, and a version of this test that
   * still passed would mean the editor was not holding the note.
   *
   * What S9 actually protects survives the inversion intact, and it is checked in two places that
   * did **not** move: the identity check over `childNodes` above, which says every node in there was
   * made by the `$effect`, and `tests/editor-container.test.ts`, which parses this component and says
   * the container has zero template children. Between them, "the body is inside the container but no
   * Svelte node put it there" is asserted from both directions. So this test's job changed from
   * "the body is outside" to "the body reached the editor and appears nowhere else", which is what
   * the read-only `<pre>` being deleted actually means.
   */
  it("puts the note body in CM6's document and nowhere else in the pane", () => {
    const target = render(EditorPane, { note: note({ body: 'MARKER-BODY' }), error: null })
    const container = target.querySelector('.editor-host')!

    expect(container.querySelector('.cm-content')!.textContent).toContain('MARKER-BODY')

    // Exactly once in the whole pane: the deleted `<pre class="body">` was a second copy of the
    // document sitting next to a live editor of it, which is a rendering of the payload rather than
    // a view of it.
    expect(target.textContent!.split('MARKER-BODY')).toHaveLength(2)
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

  it('shows the landing state instead of the note list when there is no credential', () => {
    // KAN-555 replaced the one honest paragraph this used to assert with the real landing state.
    // What is asserted here is the *shell's* half only — no sidebar, and a landing region present —
    // because everything about the paste form, the pandan link and the `401` recovery lives in
    // `tests/landing.test.ts`, which is also where the fragment sweep over those surfaces lives.
    const target = render(App, {})
    expect(target.querySelector('.landing')).not.toBeNull()
    expect(target.querySelector('[data-testid="paste-form"]')).not.toBeNull()
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
