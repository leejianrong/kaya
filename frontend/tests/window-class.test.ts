// @vitest-environment jsdom
/**
 * KAN-1818: the window size classes and the shell's per-class region map. Both are pure, so the
 * layout's decisions are testable without a browser; the e2e `mobile` project proves the CSS that
 * realises them.
 */

import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NAV_DESTINATIONS, navActive, shellRegions } from '../src/lib/shell'
import {
  BREAKPOINTS,
  WINDOW_QUERIES,
  currentWindowClass,
  watchWindowClass,
  windowClassForWidth,
} from '../src/lib/windowClass'

describe('windowClassForWidth', () => {
  it.each([
    [320, 'compact'],
    [390, 'compact'],
    [599, 'compact'],
    [600, 'medium'],
    [839, 'medium'],
    [840, 'expanded'],
    [1440, 'expanded'],
  ])('%ipx is %s', (width, expected) => {
    expect(windowClassForWidth(width)).toBe(expected)
  })

  it('uses the M3 breakpoints, and the media queries are built from the same numbers', () => {
    expect(BREAKPOINTS).toEqual({ medium: 600, expanded: 840 })
    expect(WINDOW_QUERIES.medium).toBe('(min-width: 600px)')
    expect(WINDOW_QUERIES.expanded).toBe('(min-width: 840px)')
  })
})

describe('the CSS mirrors the breakpoints', () => {
  it('only uses the breakpoints (plus the 60rem split stack) in shell CSS', () => {
    const css = [
      'src/App.svelte',
      'src/components/NavColumn.svelte',
      'src/components/Sidebar.svelte',
      'src/components/EditorPane.svelte',
      'src/components/Settings.svelte',
    ]
      .map((file) => readFileSync(file, 'utf8'))
      .join('\n')
    const widths = [...css.matchAll(/@media \((?:min|max)-width: ([^)]+)\)/g)].map((m) => m[1])
    // `max-width` for a class below a breakpoint is written as that breakpoint minus 0.02px.
    const allowed = [`${BREAKPOINTS.medium - 0.02}px`, `${BREAKPOINTS.expanded}px`, '60rem']
    for (const width of widths) {
      expect(allowed).toContain(width)
    }
    expect(widths).toContain(`${BREAKPOINTS.medium - 0.02}px`)
    expect(widths).toContain(`${BREAKPOINTS.expanded}px`)
  })
})

describe('currentWindowClass and watchWindowClass', () => {
  afterEach(() => vi.unstubAllGlobals())

  function stubMatchMedia(width: number): { set: (next: number) => void } {
    const listeners = new Set<() => void>()
    let current = width
    vi.stubGlobal('matchMedia', (query: string) => {
      const min = Number(/min-width: (\d+)px/.exec(query)![1])
      return {
        get matches() {
          return current >= min
        },
        addEventListener: (_: string, fn: () => void) => listeners.add(fn),
        removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
      }
    })
    return {
      set(next) {
        current = next
        for (const fn of listeners) fn()
      },
    }
  }

  it('is expanded where there is no matchMedia (the desktop layout is the default)', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(currentWindowClass()).toBe('expanded')
  })

  it('reads the class from matchMedia and reports changes until unsubscribed', () => {
    const screen = stubMatchMedia(390)
    expect(currentWindowClass()).toBe('compact')
    const seen: string[] = []
    const stop = watchWindowClass((next) => seen.push(next))
    screen.set(700)
    screen.set(900)
    stop()
    screen.set(300)
    expect(seen).toEqual(['medium', 'expanded'])
  })
})

describe('shellRegions', () => {
  const home = { name: 'home' } as const
  const note = { name: 'note', ref: 'NOTE-1' } as const

  it('compact: the list and the note are separate screens', () => {
    expect(shellRegions('compact', home, true)).toMatchObject({
      list: true,
      main: false,
      supporting: { kind: 'none' },
    })
    expect(shellRegions('compact', note, true)).toMatchObject({
      list: false,
      main: true,
      supporting: { kind: 'sheet' },
    })
  })

  it('compact: every non-note screen is main alone', () => {
    for (const name of ['graph', 'settings', 'tokens', 'pandan', 'device'] as const) {
      expect(shellRegions('compact', { name }, true)).toMatchObject({ list: false, main: true })
    }
  })

  it('medium and expanded keep the list beside the note; the pane goes below, then beside', () => {
    expect(shellRegions('medium', note, true)).toMatchObject({
      list: true,
      main: true,
      supporting: { kind: 'pane', placement: 'below' },
    })
    expect(shellRegions('expanded', note, true)).toMatchObject({
      list: true,
      main: true,
      supporting: { kind: 'pane', placement: 'beside' },
    })
    expect(shellRegions('expanded', home, true)).toMatchObject({
      list: true,
      main: true,
      supporting: { kind: 'none' },
    })
  })

  it('tokens and device never carry the list, at any size', () => {
    for (const cls of ['compact', 'medium', 'expanded'] as const) {
      expect(shellRegions(cls, { name: 'tokens' }, true).list).toBe(false)
      expect(shellRegions(cls, { name: 'device' }, true).list).toBe(false)
    }
  })

  it('without a credential there is no navigation, list or detail, only main', () => {
    for (const cls of ['compact', 'medium', 'expanded'] as const) {
      expect(shellRegions(cls, home, false)).toEqual({
        nav: false,
        list: false,
        main: true,
        supporting: { kind: 'none', placement: null, defaultOpen: false },
      })
    }
  })

  it('navigation is present whenever there is a credential', () => {
    expect(shellRegions('compact', home, true).nav).toBe(true)
    expect(shellRegions('compact', { name: 'tokens' }, true).nav).toBe(true)
  })
})

describe('navigation destinations', () => {
  it('are Notes, Graph and Settings, in that order', () => {
    expect(NAV_DESTINATIONS.map((d) => [d.label, d.href])).toEqual([
      ['Notes', '/'],
      ['Graph', '/graph'],
      ['Settings', '/settings'],
    ])
  })

  it('Tokens and pandan are reached through Settings, which stays active on them', () => {
    const settings = NAV_DESTINATIONS.find((d) => d.label === 'Settings')!
    for (const name of ['settings', 'tokens', 'pandan'] as const) {
      expect(navActive(settings, { name })).toBe(true)
    }
    const notes = NAV_DESTINATIONS.find((d) => d.label === 'Notes')!
    expect(navActive(notes, { name: 'home' })).toBe(true)
    expect(navActive(notes, { name: 'note', ref: 'NOTE-1' })).toBe(true)
    expect(navActive(notes, { name: 'graph' })).toBe(false)
  })
})
