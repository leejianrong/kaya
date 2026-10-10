/**
 * KAY-168: the pure helpers behind move, new folder and rename. Every move and rename is asserted
 * against `countNotes`: a note is never lost from the tree, whatever happens to its path.
 */
import { describe, expect, it } from 'vitest'

import {
  FOLDER_NAME_MAX,
  buildTree,
  childKey,
  countNotes,
  fileNameOf,
  folderNamesIn,
  folderTargets,
  movePath,
  parentOf,
  renameFolderPrefix,
  validateFolderName,
} from '../src/lib/tree'
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

const CORPUS: Note[] = [
  note('NOTE-1', 'journal/2026/a.md'),
  note('NOTE-2', 'journal/2026/b.md'),
  note('NOTE-3', 'journal/c.md'),
  note('NOTE-4', 'scratch.md'),
  note('NOTE-5', ''),
  note('NOTE-6', '', 'Hello, World!'),
]

describe('movePath', () => {
  it('keeps the filename and changes the folder', () => {
    expect(movePath(CORPUS[0], 'archive')).toBe('archive/a.md')
    expect(movePath(CORPUS[0], 'archive/old')).toBe('archive/old/a.md')
  })

  it('moves to the top level with an empty folder', () => {
    expect(movePath(CORPUS[0], '')).toBe('a.md')
  })

  it('gives a note with no filename a slug of its title plus .md', () => {
    expect(fileNameOf(CORPUS[5])).toBe('hello-world.md')
    expect(movePath(CORPUS[5], 'inbox')).toBe('inbox/hello-world.md')
    expect(movePath(CORPUS[5], '')).toBe('hello-world.md')
  })

  it('loses no note when any note moves anywhere', () => {
    for (const target of ['', 'journal', 'new/deep/er', 'journal/2026']) {
      for (const moving of CORPUS) {
        const next = CORPUS.map((n) =>
          n.ref === moving.ref ? { ...n, path: movePath(n, target) } : n,
        )
        expect(countNotes(buildTree(next))).toBe(CORPUS.length)
      }
    }
  })
})

describe('folderTargets', () => {
  it('lists every folder and ancestor, sorted, without the top level', () => {
    expect(folderTargets(CORPUS)).toEqual(['journal', 'journal/2026'])
  })

  it('includes placeholders and their ancestors', () => {
    expect(folderTargets(CORPUS, ['ideas/new'])).toEqual([
      'ideas',
      'ideas/new',
      'journal',
      'journal/2026',
    ])
  })
})

describe('placeholders in the tree', () => {
  it('adds empty folders without adding notes', () => {
    const tree = buildTree(CORPUS, ['ideas', 'journal/drafts'])
    expect(countNotes(tree)).toBe(CORPUS.length)
    expect(folderNamesIn(tree, '')).toEqual(['ideas', 'journal'])
    expect(folderNamesIn(tree, 'journal')).toEqual(['2026', 'drafts'])
  })

  it('is the same folder when notes already create it', () => {
    expect(folderNamesIn(buildTree(CORPUS, ['journal']), '')).toEqual(['journal'])
  })
})

describe('validateFolderName', () => {
  it('trims and accepts a plain name', () => {
    expect(validateFolderName('  Ideas ', [])).toEqual({ ok: true, name: 'Ideas' })
  })

  it.each([
    ['', 'needs a name'],
    ['   ', 'needs a name'],
    ['a/b', '"/"'],
    ['..', 'not a valid'],
    ['.', 'not a valid'],
    ['x'.repeat(FOLDER_NAME_MAX + 1), 'at most'],
  ])('rejects %j', (raw, fragment) => {
    const result = validateFolderName(raw, [])
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toContain(fragment)
    }
  })

  it('accepts exactly the maximum length', () => {
    expect(validateFolderName('x'.repeat(FOLDER_NAME_MAX), []).ok).toBe(true)
  })

  it('rejects a duplicate sibling, ignoring case', () => {
    expect(validateFolderName('journal', ['Journal', 'other']).ok).toBe(false)
  })
})

describe('renameFolderPrefix', () => {
  it('rewrites whole leading segments only', () => {
    expect(renameFolderPrefix('journal/2026/a.md', 'journal', 'diary')).toBe('diary/2026/a.md')
    expect(renameFolderPrefix('journal2/a.md', 'journal', 'diary')).toBeNull()
    expect(renameFolderPrefix('journal', 'journal', 'diary')).toBeNull()
  })

  it('matches a folder key itself when not strict', () => {
    expect(renameFolderPrefix('journal', 'journal', 'diary', false)).toBe('diary')
    expect(renameFolderPrefix('journal/2026', 'journal', 'diary', false)).toBe('diary/2026')
  })

  it('renaming a folder of three notes keeps all of them', () => {
    const next = CORPUS.map((n) => ({
      ...n,
      path: renameFolderPrefix(n.path, 'journal', 'diary') ?? n.path,
    }))
    expect(countNotes(buildTree(next))).toBe(CORPUS.length)
    expect(next.filter((n) => n.path.startsWith('diary/'))).toHaveLength(3)
  })
})

describe('keys', () => {
  it('childKey and parentOf are inverses', () => {
    expect(childKey('', 'a')).toBe('a')
    expect(childKey('a/b', 'c')).toBe('a/b/c')
    expect(parentOf('a/b/c')).toBe('a/b')
    expect(parentOf('a')).toBe('')
  })
})
