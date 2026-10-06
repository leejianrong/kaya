/**
 * KAN-1827: which supporting surface (backlinks + history) each window class gets, and whether it
 * starts open. Pure, so no browser: `e2e/links-sheet.spec.ts` proves the rendering.
 */
import { describe, expect, it } from 'vitest'

import {
  paneStorageKey,
  readStoredPaneOpen,
  resolvePaneOpen,
  supportingSurface,
  writeStoredPaneOpen,
} from '../src/lib/shell'

const note = { name: 'note', ref: 'NOTE-1' } as const
const classes = ['compact', 'medium', 'expanded'] as const

describe('supportingSurface', () => {
  it('is a sheet on compact, a pane below on medium, a pane beside on expanded', () => {
    expect(supportingSurface('compact', note, true)).toEqual({
      kind: 'sheet',
      placement: null,
      defaultOpen: false,
    })
    expect(supportingSurface('medium', note, true)).toEqual({
      kind: 'pane',
      placement: 'below',
      defaultOpen: false,
    })
    expect(supportingSurface('expanded', note, true)).toEqual({
      kind: 'pane',
      placement: 'beside',
      defaultOpen: false,
    })
  })

  it('is closed by default at every size, so the document keeps the width', () => {
    for (const cls of classes) {
      expect(supportingSurface(cls, note, true).defaultOpen).toBe(false)
    }
  })

  it('is none for every route that is not a note, and without a credential', () => {
    for (const cls of classes) {
      for (const name of ['home', 'graph', 'settings', 'tokens', 'pandan', 'device'] as const) {
        expect(supportingSurface(cls, { name }, true).kind).toBe('none')
      }
      expect(supportingSurface(cls, note, false).kind).toBe('none')
    }
  })
})

describe('resolvePaneOpen', () => {
  it('uses the remembered answer for a pane, else the default (closed)', () => {
    const pane = supportingSurface('expanded', note, true)
    expect(resolvePaneOpen(pane, null)).toBe(false)
    expect(resolvePaneOpen(pane, true)).toBe(true)
    expect(resolvePaneOpen(pane, false)).toBe(false)
  })

  it('never opens a sheet or nothing from a remembered value', () => {
    expect(resolvePaneOpen(supportingSurface('compact', note, true), true)).toBe(false)
    expect(resolvePaneOpen(supportingSurface('expanded', { name: 'home' }, true), true)).toBe(false)
  })
})

function memory(): Storage {
  const data = new Map<string, string>()
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  } as unknown as Storage
}

describe('the remembered pane state', () => {
  it('round-trips per window class', () => {
    const storage = memory()
    expect(readStoredPaneOpen('expanded', storage)).toBeNull()
    writeStoredPaneOpen('expanded', true, storage)
    expect(readStoredPaneOpen('expanded', storage)).toBe(true)
    expect(readStoredPaneOpen('medium', storage)).toBeNull()
    writeStoredPaneOpen('expanded', false, storage)
    expect(readStoredPaneOpen('expanded', storage)).toBe(false)
    expect(paneStorageKey('expanded')).toBe('kaya.supportPane.expanded')
  })

  it('ignores a value it does not know', () => {
    const storage = memory()
    storage.setItem(paneStorageKey('medium'), 'maybe')
    expect(readStoredPaneOpen('medium', storage)).toBeNull()
  })

  it('never throws, whatever the storage does', () => {
    const throwing = {
      getItem() {
        throw new Error('blocked')
      },
      setItem() {
        throw new Error('blocked')
      },
    } as unknown as Storage
    expect(readStoredPaneOpen('expanded', throwing)).toBeNull()
    expect(() => writeStoredPaneOpen('expanded', true, throwing)).not.toThrow()
    expect(readStoredPaneOpen('expanded', null)).toBeNull()
  })
})
