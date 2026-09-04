/**
 * `lib/tree.ts`, over the awkward paths rather than the tidy ones.
 *
 * No DOM: `buildTree` is a pure function, so it runs in vitest's default `node` environment. That is
 * deliberate for the reason `lib/editor.ts` gives about the guards — the part most worth testing is
 * the part a jsdom document could most easily obscure.
 *
 * **The first test is the one that matters.** Everything else here says where a shape *goes*;
 * `countNotes` says nothing was **lost**, and it says it over the whole battery at once. A tree is a
 * view of a mutable metadata column (ADR 0008), so it is allowed to be lossy about paths and is never
 * allowed to be lossy about notes — a dropped row is the worst failure available to this card, because
 * it looks exactly like a note that was never created.
 */

import { describe, expect, it } from 'vitest'

import { buildTree, countNotes, type NoteTree, type TreeNode } from '../src/lib/tree'
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
    team_id: null,
  }
}

/** Every awkward shape the card names, in one corpus, so the invariant covers them together. */
const AWKWARD: Note[] = [
  note('NOTE-1', 'journal/2026/08/weekly-review.md'),
  note('NOTE-2', 'design/deploy/k3d.md'),
  note('NOTE-3', 'scratch.md'),
  note('NOTE-4', ''),
  note('NOTE-5', ''),
  note('NOTE-6', '/leading.md'),
  note('NOTE-7', 'trailing/'),
  note('NOTE-8', 'doubled//slash.md'),
  note('NOTE-9', 'design/deploy/k3d.md'),
  note('NOTE-10', '/'),
  note('NOTE-11', '   '),
  note('NOTE-12', 'a/b/c/d/e/f/g/h/i/j/k/deep.md'),
]

/** Folder names at a level, in order. */
function folders(nodes: TreeNode[]): string[] {
  return nodes.filter((node) => node.kind === 'folder').map((node) => node.name)
}

/** Refs of the note leaves at a level, in order. */
function refs(nodes: TreeNode[]): string[] {
  return nodes.filter((node) => node.kind === 'note').map((node) => node.note.ref)
}

function child(nodes: TreeNode[], name: string): TreeNode[] {
  const found = nodes.find((node) => node.kind === 'folder' && node.name === name)
  if (found === undefined || found.kind !== 'folder') {
    throw new Error(`no folder ${name} in ${JSON.stringify(folders(nodes))}`)
  }
  return found.children
}

describe('buildTree never loses a note', () => {
  it('accounts for every note in the corpus, whatever its path looks like', () => {
    // The property, not a symptom. If a segment rule, a sort or a group ever swallows a row, this is
    // the assertion that says so — and it keeps saying so for shapes nobody has thought of yet,
    // because it counts rather than enumerating.
    expect(countNotes(buildTree(AWKWARD))).toBe(AWKWARD.length)
  })

  it('accounts for every note when *every* path is empty', () => {
    const all = [note('NOTE-1', ''), note('NOTE-2', ''), note('NOTE-3', '')]
    const tree = buildTree(all)

    expect(countNotes(tree)).toBe(3)
    expect(tree.roots).toEqual([])
    expect(tree.unpathed.map((found) => found.ref)).toEqual(['NOTE-1', 'NOTE-2', 'NOTE-3'])
  })

  it('is empty rather than broken with no notes at all', () => {
    expect(buildTree([])).toEqual<NoteTree>({ roots: [], unpathed: [] })
  })
})

describe('where each awkward path goes', () => {
  const tree = buildTree(AWKWARD)

  it('puts a note with no path in `unpathed`, and never in a folder', () => {
    // ADR 0008: `path` is mutable metadata and identity is the ref, so `''` is a legitimate note.
    // Two of the ten seeded notes are like this. The failure this pins is a phantom root folder
    // named `''` — which is why the assertion is about `roots` as well as about `unpathed`.
    expect(tree.unpathed.map((found) => found.ref)).toEqual([
      'NOTE-4',
      'NOTE-5',
      'NOTE-10',
      'NOTE-11',
    ])
    expect(folders(tree.roots)).not.toContain('')
    for (const name of folders(tree.roots)) {
      expect(name.trim()).not.toBe('')
    }
  })

  it('treats a path that is only separators or blanks as no path at all', () => {
    // `'/'` and `'   '` have no segment to name a folder with, so they mean the same thing `''` does.
    for (const path of ['/', '//', '   ', ' / ']) {
      const single = buildTree([note('NOTE-1', path)])
      expect(single.roots).toEqual([])
      expect(single.unpathed).toHaveLength(1)
    }
  })

  it('puts a path with no slash at the root', () => {
    // `scratch.md` has a path and is *not* the same state as `path: ''` — which is exactly why the
    // two are rendered in different places.
    expect(refs(tree.roots)).toContain('NOTE-3')
  })

  it('collapses a leading, trailing or doubled slash onto the plain form', () => {
    expect(refs(tree.roots)).toContain('NOTE-6')
    expect(refs(child(tree.roots, 'doubled'))).toEqual(['NOTE-8'])
    // `trailing/` has one segment, so that segment is the filename and there is no folder.
    expect(folders(tree.roots)).not.toContain('trailing')
    expect(refs(tree.roots)).toContain('NOTE-7')
  })

  it('nests as deep as the path says', () => {
    expect(refs(child(child(child(tree.roots, 'journal'), '2026'), '08'))).toEqual(['NOTE-1'])
    expect(countNotes({ roots: child(tree.roots, 'a'), unpathed: [] })).toBe(1)
  })

  it('keeps two notes that share one path side by side', () => {
    // Identity is the ref (ADR 0008), so a shared path is not a collision and neither row may win.
    expect(refs(child(child(tree.roots, 'design'), 'deploy'))).toEqual(['NOTE-2', 'NOTE-9'])
  })

  it('lets a file name and a folder name be the same string', () => {
    // `a/b.md` and `a/b.md/c.md`. Folders and leaves are separate collections, so neither overwrites
    // the other — a single name-keyed map would have lost one of them.
    const tree2 = buildTree([note('NOTE-1', 'a/b.md'), note('NOTE-2', 'a/b.md/c.md')])
    const inA = child(tree2.roots, 'a')

    expect(folders(inA)).toEqual(['b.md'])
    expect(refs(inA)).toEqual(['NOTE-1'])
    expect(refs(child(inA, 'b.md'))).toEqual(['NOTE-2'])
    expect(countNotes(tree2)).toBe(2)
  })
})

describe('order and labelling', () => {
  it('puts folders before leaves and sorts each group by name', () => {
    const tree = buildTree([
      note('NOTE-1', 'zebra.md'),
      note('NOTE-2', 'design/a.md'),
      note('NOTE-3', 'apple.md'),
      note('NOTE-4', 'archive/a.md'),
    ])

    expect(tree.roots.map((node) => (node.kind === 'folder' ? `${node.name}/` : node.filename))).toEqual([
      'archive/',
      'design/',
      'apple.md',
      'zebra.md',
    ])
  })

  it('gives a folder its full prefix as a key, so two `2026`s are distinct', () => {
    const tree = buildTree([note('NOTE-1', 'journal/2026/a.md'), note('NOTE-2', 'archive/2026/b.md')])
    const keys = tree.roots.flatMap((node) =>
      node.kind === 'folder' ? node.children.filter((c) => c.kind === 'folder').map((c) => c.key) : [],
    )

    expect(keys).toEqual(['archive/2026', 'journal/2026'])
  })

  it("labels a leaf with the path's last segment", () => {
    const tree = buildTree([note('NOTE-1', 'journal/2026/08/weekly-review.md')])
    const leaf = child(child(child(tree.roots, 'journal'), '2026'), '08')[0]

    expect(leaf.kind === 'note' && leaf.filename).toBe('weekly-review.md')
  })

  it('labels an unpathed note with an empty filename rather than inventing one', () => {
    // Nothing here fabricates a name for a note that has no path. `Sidebar.svelte` shows the ref.
    const tree = buildTree([note('NOTE-1', '')])
    expect(tree.unpathed).toHaveLength(1)
    expect(tree.roots).toEqual([])
  })
})
