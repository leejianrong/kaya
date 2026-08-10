/**
 * The folder tree, as a **view of the `path` column** and nothing else.
 *
 * ADR 0008: a note's identity is its `NOTE-n` ref, `path` is mutable metadata, and moving a note is a
 * `PATCH` to one column with no link rewriting. Two things follow, and they are the whole design of
 * this module:
 *
 * - **There is no folder table and there must never be one.** A folder here exists because some note
 *   has a path with that segment in it, and it stops existing the moment the last such note moves.
 *   Nothing is persisted, nothing is created, and a "create folder" affordance would be a lie about
 *   the schema.
 * - **A note is never keyed on its path.** Two notes may share one, a note may have none, and neither
 *   is a conflict — the ref tells them apart. So the leaves below carry whole `Note`s and the tree is
 *   free to be lossy about *paths* while being lossless about *notes*.
 *
 * That second property is the one worth a test rather than a sentence: `countNotes(buildTree(xs))`
 * equals `xs.length` for every corpus, which is what makes "a tree that silently drops a note" a red
 * build instead of a support question. It is asserted over the awkward shapes in
 * `tests/tree.test.ts`, and the awkward shapes are the point — two of the ten seeded notes have
 * `path: ''`.
 *
 * Pure functions, no DOM, no reactivity: `Sidebar.svelte` renders what comes out of here and decides
 * nothing about structure.
 */

import type { Note } from './types'

/** A path segment that some note lives under. Synthesised, never stored. */
export interface FolderNode {
  kind: 'folder'
  /** The segment itself, e.g. `2026`. */
  name: string
  /** The full prefix, e.g. `journal/2026` — a stable `{#each}` key and the collapse-state key. */
  key: string
  children: TreeNode[]
}

/** One note, at the end of its path. */
export interface NoteLeaf {
  kind: 'note'
  note: Note
  /**
   * The path's last segment, e.g. `weekly-review.md`, or `''` for a note with no path.
   *
   * Not the title: the title is what `Sidebar.svelte` shows as the row's name, and this is the
   * filename beside it. A row that showed only the title would make two notes called "Notes" in
   * different folders indistinguishable.
   */
  filename: string
}

export type TreeNode = FolderNode | NoteLeaf

/**
 * A whole tree: the roots, plus the notes that have no path at all.
 *
 * `unpathed` is a **separate field rather than a folder**, and this is the decision the card is most
 * exposed on. A note with `path: ''` is legitimate (ADR 0008) and two of the seeded notes are like
 * that. The two wrong answers are dropping them — losing notes silently, the worst failure available
 * here — and inventing a root folder named `''` or `/`, which claims the data says something it does
 * not. A named field forces `Sidebar.svelte` to render them under a label that reads as the *absence*
 * of a path rather than as a folder, and makes forgetting them a type error rather than an omission.
 */
export interface NoteTree {
  roots: TreeNode[]
  unpathed: Note[]
}

/**
 * Group notes by their path.
 *
 * Every awkward shape is decided here rather than discovered later:
 *
 * | Path | Where it goes |
 * |---|---|
 * | `journal/2026/08/weekly.md` | nested three deep, leaf `weekly.md` |
 * | `scratch.md` (no `/`) | a root-level leaf |
 * | `''` | `unpathed` |
 * | `'/'`, `'//'`, `'   '` | `unpathed` — there is no segment to name a folder with |
 * | `/design/deploy.md` (leading `/`) | same as `design/deploy.md` |
 * | `design/deploy/` (trailing `/`) | a leaf named `deploy` inside `design` |
 * | `design//deploy.md` (doubled) | same as `design/deploy.md` |
 * | two notes, one path | two leaves, side by side, told apart by ref |
 * | `a/b.md` and `a/b.md/c.md` | folder `a` holds a leaf `b.md` **and** a folder `b.md` |
 *
 * The last row is why folders and leaves are collected separately: a name is not a key across both
 * kinds, so a file and a directory sharing a name cannot overwrite each other. An empty or
 * whitespace-only segment is dropped, which is what collapses a leading, trailing or doubled slash
 * onto the plain form; a path that is *entirely* separators or blanks therefore has no segments left
 * and is `unpathed`, which is the same place `''` goes and the same thing it means.
 */
export function buildTree(notes: Note[]): NoteTree {
  const root: Builder = { folders: new Map(), leaves: [] }
  const unpathed: Note[] = []

  for (const note of notes) {
    const segments = note.path.split('/').filter((segment) => segment.trim() !== '')
    if (segments.length === 0) {
      unpathed.push(note)
      continue
    }

    const filename = segments[segments.length - 1]
    let level = root
    let prefix = ''
    for (const segment of segments.slice(0, -1)) {
      prefix = prefix === '' ? segment : `${prefix}/${segment}`
      let next = level.folders.get(segment)
      if (next === undefined) {
        next = { folders: new Map(), leaves: [], key: prefix }
        level.folders.set(segment, next)
      }
      level = next
    }
    level.leaves.push({ kind: 'note', note, filename })
  }

  return { roots: finish(root), unpathed }
}

/** Every note in the tree, leaves and unpathed together. The lossless-about-notes invariant. */
export function countNotes(tree: NoteTree): number {
  const walk = (nodes: TreeNode[]): number =>
    nodes.reduce((total, node) => total + (node.kind === 'folder' ? walk(node.children) : 1), 0)
  return walk(tree.roots) + tree.unpathed.length
}

interface Builder {
  folders: Map<string, Builder>
  leaves: NoteLeaf[]
  key?: string
}

/**
 * Turn the builder into sorted `TreeNode`s: folders first, then leaves.
 *
 * Folders before files is the convention every file browser uses, and the alternative — one
 * alphabetical run — puts `design/` between `apple.md` and `zebra.md` where nobody looks for it.
 * Within each group, `localeCompare` on the displayed name, then the ref, so two notes with the same
 * path have a stable order rather than a fetch-order-dependent one.
 */
function finish(level: Builder): TreeNode[] {
  const folders: FolderNode[] = Array.from(level.folders.entries())
    .map(([name, child]) => ({
      kind: 'folder' as const,
      name,
      key: child.key ?? name,
      children: finish(child),
    }))
    .sort((left, right) => left.name.localeCompare(right.name))

  const leaves = [...level.leaves].sort(
    (left, right) =>
      left.filename.localeCompare(right.filename) || left.note.ref.localeCompare(right.note.ref),
  )

  return [...folders, ...leaves]
}
