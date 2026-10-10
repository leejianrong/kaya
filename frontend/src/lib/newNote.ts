/**
 * The title and path a "New note" starts with (KAY-166).
 *
 * Obsidian-style: the note exists the instant the button is pressed, called `Untitled` (the API
 * refuses an empty title), and the person names it afterwards in the title field the editor focuses.
 * Pure and synchronous so it is unit-tested without a browser; `App.svelte` supplies the loaded
 * notes and the folder context and sends the result straight to `createNote()`.
 *
 * A note is identified by its `NOTE-n` ref, never by its title or path (ADR 0008), so a collision is
 * only ever cosmetic. It is still avoided: two rows both called `Untitled` are indistinguishable.
 */
import type { Note } from './types'

export const UNTITLED = 'Untitled'

export interface NewNote {
  title: string
  /** `<folder>/<slug>.md`, or `<slug>.md` when there is no folder. Never empty. */
  path: string
}

/** A file-name stem for a title: lowercase, runs of anything but letters/digits become one `-`. */
export function slugify(title: string): string {
  const slug = title
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug === '' ? 'untitled' : slug
}

/** Segments of a path with blanks and doubled separators dropped, as `lib/tree.ts` reads one. */
function segments(path: string): string[] {
  return path
    .split('/')
    .map((segment) => segment.trim())
    .filter((segment) => segment !== '')
}

/** The folder part of a note path (`journal/2026/a.md` -> `journal/2026`), `''` for none. */
export function folderOf(path: string): string {
  return segments(path).slice(0, -1).join('/')
}

/**
 * Title and path for a new note in `folder`.
 *
 * `Untitled`, then `Untitled 1`, `Untitled 2`... — the first number whose title (case-insensitive,
 * across every loaded note) and whose path (within the folder) are both unused.
 */
export function newNoteDraft(notes: readonly Note[], folder: string): NewNote {
  const dir = segments(folder).join('/')
  const prefix = dir === '' ? '' : `${dir}/`
  const titles = new Set(notes.map((note) => note.title.trim().toLowerCase()))
  const paths = new Set(notes.map((note) => segments(note.path).join('/').toLowerCase()))

  for (let n = 0; ; n += 1) {
    const title = n === 0 ? UNTITLED : `${UNTITLED} ${n}`
    const path = `${prefix}${slugify(title)}.md`
    if (!titles.has(title.toLowerCase()) && !paths.has(path.toLowerCase())) {
      return { title, path }
    }
  }
}
