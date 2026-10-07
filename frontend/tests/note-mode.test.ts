// @vitest-environment jsdom
/**
 * KAN-1819: the Read | Edit | Split decisions, all pure. Which modes a window class offers, what a
 * note opens in, what a stored value is allowed to mean, and where the choice is remembered.
 * `e2e/note-mode.spec.ts` proves the layout that realises them.
 */

import { afterEach, describe, expect, it } from 'vitest'

import {
  MODES,
  availableModes,
  defaultMode,
  modeAvailable,
  modeStorageKey,
  readStoredMode,
  resolveMode,
  writeStoredMode,
} from '../src/lib/noteMode'

describe('modeAvailable', () => {
  it('offers Split only at expanded', () => {
    expect(modeAvailable('split', 'expanded')).toBe(true)
    expect(modeAvailable('split', 'medium')).toBe(false)
    expect(modeAvailable('split', 'compact')).toBe(false)
  })

  it.each(['compact', 'medium', 'expanded'] as const)('offers Read and Edit at %s', (wc) => {
    expect(modeAvailable('read', wc)).toBe(true)
    expect(modeAvailable('edit', wc)).toBe(true)
  })

  it('lists the modes in switch order, leaving Split out below expanded', () => {
    expect(MODES).toEqual(['read', 'edit', 'split'])
    expect(availableModes('expanded')).toEqual(['read', 'edit', 'split'])
    expect(availableModes('medium')).toEqual(['read', 'edit'])
    expect(availableModes('compact')).toEqual(['read', 'edit'])
  })
})

describe('defaultMode', () => {
  it('is Edit on expanded, whatever the note', () => {
    expect(defaultMode('expanded', false)).toBe('edit')
    expect(defaultMode('expanded', true)).toBe('edit')
  })

  it('is Read for a saved note on compact and medium', () => {
    expect(defaultMode('compact', false)).toBe('read')
    expect(defaultMode('medium', false)).toBe('read')
  })

  it('is Edit for a note just created on compact and medium', () => {
    expect(defaultMode('compact', true)).toBe('edit')
    expect(defaultMode('medium', true)).toBe('edit')
  })
})

describe('resolveMode', () => {
  it('takes the remembered mode when there is one', () => {
    expect(resolveMode({ windowClass: 'compact', stored: 'edit', justCreated: false })).toBe('edit')
    expect(resolveMode({ windowClass: 'expanded', stored: 'read', justCreated: false })).toBe('read')
    expect(resolveMode({ windowClass: 'expanded', stored: 'split', justCreated: false })).toBe(
      'split',
    )
  })

  it('falls back to the default with nothing remembered', () => {
    expect(resolveMode({ windowClass: 'compact', stored: null, justCreated: false })).toBe('read')
    expect(resolveMode({ windowClass: 'expanded', stored: null, justCreated: false })).toBe('edit')
  })

  it.each(['bogus', '', 'READ', 7, {}, undefined])(
    'clamps an invalid stored value (%o) to the default',
    (stored) => {
      expect(resolveMode({ windowClass: 'compact', stored, justCreated: false })).toBe('read')
      expect(resolveMode({ windowClass: 'expanded', stored, justCreated: false })).toBe('edit')
    },
  )

  it('refuses a stored Split where it is not offered, landing on Edit', () => {
    expect(resolveMode({ windowClass: 'medium', stored: 'split', justCreated: false })).toBe('edit')
    expect(resolveMode({ windowClass: 'compact', stored: 'split', justCreated: true })).toBe('edit')
  })

  it('opens a just-created note in Edit below expanded even if Read was remembered', () => {
    expect(resolveMode({ windowClass: 'compact', stored: 'read', justCreated: true })).toBe('edit')
    expect(resolveMode({ windowClass: 'medium', stored: 'read', justCreated: true })).toBe('edit')
  })

  it('lets the expanded remembered choice stand for a just-created note', () => {
    expect(resolveMode({ windowClass: 'expanded', stored: 'read', justCreated: true })).toBe('read')
  })
})

describe('storage', () => {
  afterEach(() => localStorage.clear())

  it('keeps one key per size class, compact and medium apart', () => {
    const keys = (['compact', 'medium', 'expanded'] as const).map(modeStorageKey)
    expect(new Set(keys).size).toBe(3)
    expect(keys.every((key) => key.startsWith('kaya.'))).toBe(true)
  })

  it('round-trips a choice per class', () => {
    writeStoredMode('compact', 'edit')
    writeStoredMode('expanded', 'split')
    expect(readStoredMode('compact')).toBe('edit')
    expect(readStoredMode('expanded')).toBe('split')
    expect(readStoredMode('medium')).toBeNull()
  })

  it('answers null for garbage rather than throwing', () => {
    localStorage.setItem(modeStorageKey('compact'), 'sideways')
    expect(readStoredMode('compact')).toBeNull()
  })

  it('survives a storage that throws, on read and on write', () => {
    const broken = {
      getItem() {
        throw new Error('blocked')
      },
      setItem() {
        throw new Error('blocked')
      },
    } as unknown as Storage
    expect(readStoredMode('compact', broken)).toBeNull()
    expect(() => writeStoredMode('compact', 'edit', broken)).not.toThrow()
  })

  it('survives there being no storage at all', () => {
    expect(readStoredMode('compact', null)).toBeNull()
    expect(() => writeStoredMode('compact', 'edit', null)).not.toThrow()
  })
})
