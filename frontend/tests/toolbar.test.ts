/**
 * KAN-1826: when the formatting toolbar is on screen, and the buttons it has.
 */
import { describe, expect, it } from 'vitest'

import { TOOLBAR_BUTTONS, toolbarShown } from '../src/lib/toolbar'

describe('TOOLBAR_BUTTONS', () => {
  it('is the eight actions of the card, in order, each with an accessible name', () => {
    expect(TOOLBAR_BUTTONS.map((button) => button.action)).toEqual([
      'bold',
      'italic',
      'list',
      'checkbox',
      'code',
      'link',
      'wikilink',
      'undo',
    ])
    for (const button of TOOLBAR_BUTTONS) {
      expect(button.label.length).toBeGreaterThan(3)
    }
  })
})

describe('toolbarShown', () => {
  const base = { windowClass: 'compact', mode: 'edit', focused: true, inNote: true } as const

  it('shows while editing a focused note on a phone or a tablet', () => {
    expect(toolbarShown(base)).toBe(true)
    expect(toolbarShown({ ...base, windowClass: 'medium' })).toBe(true)
  })

  it('does not show on a desktop-sized window', () => {
    expect(toolbarShown({ ...base, windowClass: 'expanded' })).toBe(false)
  })

  it('does not show in Read, or without focus in the editor, or outside a note', () => {
    expect(toolbarShown({ ...base, mode: 'read' })).toBe(false)
    expect(toolbarShown({ ...base, focused: false })).toBe(false)
    expect(toolbarShown({ ...base, inNote: false })).toBe(false)
  })
})
