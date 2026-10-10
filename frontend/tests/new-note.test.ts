import { describe, expect, it } from 'vitest'

import { folderOf, newNoteDraft, slugify } from '../src/lib/newNote'
import type { Note } from '../src/lib/types'

function note(title: string, path = ''): Note {
  return {
    ref: 'NOTE-1',
    id: 1,
    title,
    body: '',
    path,
    created_at: '',
    updated_at: '',
    team_id: null,
  }
}

describe('newNoteDraft', () => {
  it('starts at Untitled with no folder', () => {
    expect(newNoteDraft([], '')).toEqual({ title: 'Untitled', path: 'untitled.md' })
  })

  it('counts up past taken titles', () => {
    const notes = [note('Untitled'), note('untitled 1')]
    expect(newNoteDraft(notes, '')).toEqual({ title: 'Untitled 2', path: 'untitled-2.md' })
  })

  it('fills a gap rather than always appending', () => {
    expect(newNoteDraft([note('Untitled'), note('Untitled 2')], '').title).toBe('Untitled 1')
  })

  it('puts the file in the folder', () => {
    expect(newNoteDraft([], 'projects/kaya')).toEqual({
      title: 'Untitled',
      path: 'projects/kaya/untitled.md',
    })
  })

  it('skips a number whose path is taken, even under another title', () => {
    const notes = [note('Renamed', 'projects/kaya/untitled.md')]
    expect(newNoteDraft(notes, 'projects/kaya')).toEqual({
      title: 'Untitled 1',
      path: 'projects/kaya/untitled-1.md',
    })
  })

  it('normalises odd folder names', () => {
    expect(newNoteDraft([], '/a//b /').path).toBe('a/b/untitled.md')
    expect(newNoteDraft([], '  ').path).toBe('untitled.md')
    expect(newNoteDraft([], 'my folder/日本語').path).toBe('my folder/日本語/untitled.md')
  })

  it('treats a title collision as global, across folders', () => {
    expect(newNoteDraft([note('Untitled', 'other/x.md')], 'mine').title).toBe('Untitled 1')
  })
})

describe('slugify and folderOf', () => {
  it('slugifies', () => {
    expect(slugify('Untitled 12')).toBe('untitled-12')
    expect(slugify('  Café -- Notes!  ')).toBe('cafe-notes')
    expect(slugify('日本語')).toBe('untitled')
  })

  it('finds a folder', () => {
    expect(folderOf('journal/2026/a.md')).toBe('journal/2026')
    expect(folderOf('a.md')).toBe('')
    expect(folderOf('')).toBe('')
    expect(folderOf('/x//y.md')).toBe('x')
  })
})
