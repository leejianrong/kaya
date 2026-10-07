/** KAN-1827: the pure helpers behind the bottom sheet and its tabs. */
import { describe, expect, it } from 'vitest'

import { DISMISS_DRAG_PX, shouldDismissDrag, wrapFocusIndex } from '../src/lib/sheet'
import { nextTabIndex } from '../src/lib/tabs'

describe('nextTabIndex (ARIA tabs, horizontal)', () => {
  it('moves right and left, wrapping at both ends', () => {
    expect(nextTabIndex('ArrowRight', 0, 2)).toBe(1)
    expect(nextTabIndex('ArrowRight', 1, 2)).toBe(0)
    expect(nextTabIndex('ArrowLeft', 1, 2)).toBe(0)
    expect(nextTabIndex('ArrowLeft', 0, 2)).toBe(1)
  })

  it('jumps to the first and last on Home and End', () => {
    expect(nextTabIndex('Home', 1, 3)).toBe(0)
    expect(nextTabIndex('End', 0, 3)).toBe(2)
  })

  it('answers null for any other key, so the caller leaves the event alone', () => {
    expect(nextTabIndex('Enter', 0, 2)).toBeNull()
    expect(nextTabIndex('ArrowDown', 0, 2)).toBeNull()
    expect(nextTabIndex('a', 0, 2)).toBeNull()
  })
})

describe('wrapFocusIndex (the sheet keeps Tab inside)', () => {
  it('wraps forward off the last and backward off the first', () => {
    expect(wrapFocusIndex(2, 3, false)).toBe(0)
    expect(wrapFocusIndex(0, 3, true)).toBe(2)
  })

  it('answers null in the middle, where the browser already does the right thing', () => {
    expect(wrapFocusIndex(1, 3, false)).toBeNull()
    expect(wrapFocusIndex(1, 3, true)).toBeNull()
  })

  it('treats focus outside the list as the start', () => {
    expect(wrapFocusIndex(-1, 3, false)).toBe(0)
    expect(wrapFocusIndex(-1, 3, true)).toBe(2)
    expect(wrapFocusIndex(0, 0, false)).toBeNull()
  })
})

describe('shouldDismissDrag', () => {
  it('dismisses on a downward drag past the threshold only', () => {
    expect(shouldDismissDrag(DISMISS_DRAG_PX)).toBe(true)
    expect(shouldDismissDrag(DISMISS_DRAG_PX - 1)).toBe(false)
    expect(shouldDismissDrag(-300)).toBe(false)
  })
})
