// @vitest-environment jsdom
/**
 * KAN-1826: how far the soft keyboard (or anything else) covers the layout viewport, from the
 * numbers `visualViewport` reports. Pure arithmetic plus one small subscription.
 */
import { describe, expect, it, vi } from 'vitest'

import {
  KEYBOARD_MIN_INSET,
  keyboardInset,
  keyboardOpen,
  readViewport,
  watchViewport,
} from '../src/lib/viewport'

describe('keyboardInset', () => {
  it('is zero when the visual viewport fills the layout viewport', () => {
    expect(keyboardInset(800, { height: 800, offsetTop: 0, scale: 1 })).toBe(0)
  })

  it('is the covered strip at the bottom', () => {
    expect(keyboardInset(800, { height: 500, offsetTop: 0, scale: 1 })).toBe(300)
  })

  it('accounts for the page having scrolled inside the visual viewport (iOS)', () => {
    expect(keyboardInset(800, { height: 500, offsetTop: 120, scale: 1 })).toBe(180)
  })

  it('never goes negative', () => {
    expect(keyboardInset(800, { height: 820, offsetTop: 0, scale: 1 })).toBe(0)
  })

  it('ignores a pinch zoom, which also shrinks the visual viewport', () => {
    expect(keyboardInset(800, { height: 400, offsetTop: 0, scale: 2 })).toBe(0)
  })

  it('is zero without a visual viewport', () => {
    expect(keyboardInset(800, null)).toBe(0)
  })

  it('rounds to whole pixels', () => {
    expect(keyboardInset(800, { height: 500.4, offsetTop: 0, scale: 1 })).toBe(300)
  })
})

describe('keyboardOpen', () => {
  it('treats a small inset as browser chrome, not a keyboard', () => {
    expect(keyboardOpen(KEYBOARD_MIN_INSET - 1)).toBe(false)
    expect(keyboardOpen(KEYBOARD_MIN_INSET)).toBe(true)
  })
})

describe('readViewport', () => {
  it('is null where visualViewport is missing', () => {
    expect(readViewport({ innerHeight: 800 } as unknown as Window)).toBeNull()
  })
})

describe('watchViewport', () => {
  function fakeWindow(vv: { height: number; offsetTop: number; scale: number }) {
    const listeners = new Map<string, Set<() => void>>()
    const target = {
      innerHeight: 800,
      visualViewport: {
        ...vv,
        addEventListener: (type: string, fn: () => void) => {
          if (!listeners.has(type)) listeners.set(type, new Set())
          listeners.get(type)!.add(fn)
        },
        removeEventListener: (type: string, fn: () => void) => listeners.get(type)?.delete(fn),
      },
    }
    return {
      win: target as unknown as Window,
      vv: target.visualViewport,
      fire: (type: string) => listeners.get(type)?.forEach((fn) => fn()),
      count: () => [...listeners.values()].reduce((n, set) => n + set.size, 0),
    }
  }

  it('reports once on subscribe and again on resize and scroll', () => {
    const fake = fakeWindow({ height: 800, offsetTop: 0, scale: 1 })
    const seen: number[] = []
    watchViewport((inset) => seen.push(inset), fake.win)
    expect(seen).toEqual([0])
    fake.vv.height = 500
    fake.fire('resize')
    fake.vv.offsetTop = 100
    fake.fire('scroll')
    expect(seen).toEqual([0, 300, 200])
  })

  it('does not repeat an unchanged inset', () => {
    const fake = fakeWindow({ height: 500, offsetTop: 0, scale: 1 })
    const onInset = vi.fn()
    watchViewport(onInset, fake.win)
    fake.fire('resize')
    fake.fire('scroll')
    expect(onInset).toHaveBeenCalledTimes(1)
  })

  it('unsubscribes', () => {
    const fake = fakeWindow({ height: 800, offsetTop: 0, scale: 1 })
    const stop = watchViewport(() => undefined, fake.win)
    expect(fake.count()).toBe(2)
    stop()
    expect(fake.count()).toBe(0)
  })

  it('reports zero once and subscribes to nothing where visualViewport is missing', () => {
    const onInset = vi.fn()
    const stop = watchViewport(onInset, { innerHeight: 800 } as unknown as Window)
    expect(onInset).toHaveBeenCalledExactlyOnceWith(0)
    stop()
  })
})
