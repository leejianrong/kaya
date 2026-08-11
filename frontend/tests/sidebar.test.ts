// @vitest-environment jsdom
/**
 * `Sidebar.svelte` — the folder tree and the flat list, as rendered.
 *
 * `tests/tree.test.ts` owns the grouping; this owns what reaches the screen. The split matters
 * because CLAUDE.md's rule about structural guards cuts both ways: `countNotes` proves the *tree
 * value* holds every note, and it stays green while a component renders only half of it. The
 * on-screen count of note links is a different assertion and it needs its own test.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import Sidebar from '../src/components/Sidebar.svelte'
import type { Route } from '../src/lib/router'
import type { Note } from '../src/lib/types'

function note(ref: string, path: string, title = `Title ${ref}`): Note {
  return {
    ref,
    id: Number.parseInt(ref.replace(/\D/g, ''), 10),
    title,
    body: '',
    path,
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
  }
}

/** The ten seeded notes' shape, plus the awkward paths this card had to decide about. */
const NOTES: Note[] = [
  note('NOTE-1', 'journal/2026/08/weekly-review.md'),
  note('NOTE-2', 'design/deploy/k3d.md'),
  note('NOTE-3', 'scratch.md'),
  note('NOTE-4', '', 'No path at all'),
  note('NOTE-5', '', 'Also no path'),
  note('NOTE-6', 'design/adr.md'),
  note('NOTE-7', 'a/b/c/d/e/f/g/h/i/j/k/l/deep.md'),
]

let host: HTMLDivElement
const mounted: unknown[] = []

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
})

function render(notes: Note[], route: Route = { name: 'home' }, loading = false): HTMLDivElement {
  mounted.push(mount(Sidebar, { target: host, props: { notes, route, loading } }))
  flushSync()
  return host
}

/** Every note link in the sidebar, by the ref its href addresses. */
function links(): string[] {
  return Array.from(host.querySelectorAll<HTMLAnchorElement>('a[href^="/notes/"]')).map((anchor) =>
    anchor.getAttribute('href')!.replace('/notes/', ''),
  )
}

/** The folder row named `name`. Matched on its `.title` span, not on the row's whole text, because
 *  the row also holds the twist glyph. */
function folder(name: string): HTMLButtonElement {
  const found = Array.from(host.querySelectorAll<HTMLButtonElement>('button.folder')).find(
    (button) => button.querySelector('.title')?.textContent?.trim() === name,
  )
  expect(found, `no folder row named ${name}`).not.toBeUndefined()
  return found!
}

function switchTo(view: 'Tree' | 'List'): void {
  const button = Array.from(host.querySelectorAll('button')).find(
    (candidate) => candidate.textContent?.trim() === view,
  )
  expect(button).not.toBeUndefined()
  button!.click()
  flushSync()
}

describe('the note list', () => {
  it('shows every note the API returned, in that order', () => {
    render(NOTES)
    switchTo('List')

    // The list is the corpus, unsorted and ungrouped, which is exactly why it exists beside the tree:
    // "the tree is hiding a note" is one click from being disproved.
    expect(host.querySelector('[data-testid="note-list"]')).not.toBeNull()
    expect(links()).toEqual(NOTES.map((found) => found.ref))
  })

  it('shows an em dash rather than a blank line for a note with no path', () => {
    render([note('NOTE-4', '', 'No path at all')])
    switchTo('List')

    expect(host.textContent).toContain('No path at all')
    expect(host.textContent).toContain('—')
  })

  it('marks the open note as the current page', () => {
    render(NOTES, { name: 'note', ref: 'NOTE-3' })
    switchTo('List')

    const current = host.querySelectorAll('a[aria-current="page"]')
    expect(current).toHaveLength(1)
    expect(current[0].getAttribute('href')).toBe('/notes/NOTE-3')
  })

  it('says so while loading and when there is nothing', () => {
    render([], { name: 'home' }, true)
    expect(host.textContent).toContain('Loading')

    for (const instance of mounted.splice(0)) {
      unmount(instance as never)
    }
    render([])
    expect(host.textContent).toContain('No notes yet')
  })
})

describe('the folder tree', () => {
  it('is the default view', () => {
    render(NOTES)
    expect(host.querySelector('[data-testid="note-tree"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="note-list"]')).toBeNull()
  })

  it('shows every note exactly once, tree rows and unpathed rows together', () => {
    render(NOTES)

    // The rendered twin of `countNotes`. A note reachable in the tree *value* but not on the screen —
    // a collapsed group rendered as nothing, a snippet that forgot a branch — is invisible to
    // `tests/tree.test.ts` and would land as "my note disappeared".
    expect(links().sort()).toEqual(NOTES.map((found) => found.ref).sort())
  })

  it('nests real folders and labels a leaf with its filename', () => {
    render(NOTES)

    // `journal` → `2026` → `08` → the note. Three nested lists, not three sibling rows.
    const branch = folder('journal').closest('li')!
    expect(branch.querySelector('ul li ul li a[href="/notes/NOTE-1"]')).not.toBeNull()
    expect(branch.textContent).toContain('weekly-review.md')
  })

  it('puts a note with no path under a group labelled as the absence of one', () => {
    // ADR 0008: `path` is mutable metadata and identity is the ref, so `path: ''` is a legitimate
    // note — two of the ten seeded ones are. The two failures available were dropping them and
    // inventing a folder named `''`; this asserts against both, and that the group *says* what it is.
    render(NOTES)
    const group = host.querySelector('[data-testid="unpathed"]')

    expect(group).not.toBeNull()
    expect(group!.textContent).toContain('no path')
    expect(group!.textContent).toContain('2')
    expect(group!.querySelectorAll('a[href^="/notes/"]')).toHaveLength(2)
    expect(group!.textContent).toContain('No path at all')
    // The ref stands in for the filename it has none of, rather than a blank or a made-up name.
    expect(group!.textContent).toContain('NOTE-4')

    // And no folder row is an empty or whitespace-only name.
    for (const button of host.querySelectorAll('[data-testid="note-tree"] button')) {
      expect(button.textContent?.replace(/[▸▾]/g, '').trim()).not.toBe('')
    }
  })

  it('omits the unpathed group entirely when every note has a path', () => {
    render([note('NOTE-1', 'a/b.md')])
    expect(host.querySelector('[data-testid="unpathed"]')).toBeNull()
  })

  it('puts a path with no slash at the top level, distinct from having no path', () => {
    render(NOTES)
    const tree = host.querySelector('[data-testid="note-tree"]')!

    // `scratch.md` is a direct child of the tree's root list; the unpathed group is a sibling of the
    // whole tree, so the two states are visibly different places.
    expect(tree.querySelector(':scope > li > a[href="/notes/NOTE-3"]')).not.toBeNull()
    expect(tree.querySelector('a[href="/notes/NOTE-4"]')).toBeNull()
  })

  it('collapses and expands a folder, and starts expanded', () => {
    render(NOTES)
    const design = folder('design')

    // Expanded by default: a tree that starts collapsed makes a loaded sidebar look empty.
    expect(design.getAttribute('aria-expanded')).toBe('true')
    expect(links()).toContain('NOTE-6')

    design.click()
    flushSync()
    expect(design.getAttribute('aria-expanded')).toBe('false')
    expect(links()).not.toContain('NOTE-6')
    // Collapsing one folder hides only its own notes.
    expect(links()).toContain('NOTE-1')

    design.click()
    flushSync()
    expect(links()).toContain('NOTE-6')
  })

  it('stops indenting before a deep path runs off the pane', () => {
    render(NOTES)
    const insets = Array.from(host.querySelectorAll<HTMLElement>('.row')).map((row) =>
      Number.parseFloat(row.style.paddingLeft),
    )

    // `path` is `String(1024)` in migration `0001`, so nesting is unbounded and the indent is not.
    // The clamp is at eight levels: `0.5 + 8 * 0.7`.
    expect(Math.max(...insets)).toBeLessThanOrEqual(0.5 + 8 * 0.7)
    // …but it does indent: a flat tree would be a bug of the opposite kind.
    expect(Math.max(...insets)).toBeGreaterThan(0.5)
  })

  it('keeps two notes that share a path side by side', () => {
    render([note('NOTE-1', 'design/deploy/k3d.md'), note('NOTE-2', 'design/deploy/k3d.md')])
    expect(links().sort()).toEqual(['NOTE-1', 'NOTE-2'])
  })

  it('falls back to the ref when a note has no title', () => {
    // `title` is `String(255)` and the API accepts `''`, so a row must never be a blank line.
    render([note('NOTE-9', 'a/b.md', '')])
    expect(host.querySelector('a[href="/notes/NOTE-9"]')?.textContent).toContain('NOTE-9')
  })
})
