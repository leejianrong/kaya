// @vitest-environment jsdom
/**
 * KAN-969: `lib/router.ts`'s single navigation choke point, and the guard slot that makes it one.
 *
 * FOUND BY THE KAN-568 AGENT, then confirmed for all three link surfaces: a click on any internal
 * link — the sidebar's flat list, its folder tree, and the backlinks rail all reduce to the same call,
 * `interceptClick(event, path)` — discarded whatever the editor held, silently, no dialog. The fix
 * belongs here rather than at each of those call sites, because they already share one function; this
 * file proves the property at the layer it actually lives, so `Sidebar.svelte` and
 * `BacklinksPanel.svelte` need no test of their own and, not incidentally, no code change either — this
 * card touches neither file.
 *
 * The guard itself is tested as a **plain function**, deliberately decoupled from `window.confirm`:
 * `router.ts` does not know or care *how* the registered guard decides, only that it is consulted, and
 * a test that stubbed `confirm` here would be testing `App.svelte`'s choice rather than this module's
 * contract. `tests/unsaved-navigation.test.ts` is where the `confirm()` wiring itself is proved, end to
 * end, through a mounted `App`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { interceptClick, navigate, onNavigate, setNavigationGuard } from '../src/lib/router'

function click(overrides: Partial<MouseEvent> = {}): MouseEvent {
  return {
    defaultPrevented: false,
    button: 0,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    preventDefault: vi.fn(),
    ...overrides,
  } as unknown as MouseEvent
}

beforeEach(() => {
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  // The guard slot is module-level state shared by every test in this process (the same reason
  // `App.svelte` unregisters its own guard on unmount) — leaving one behind here would answer a
  // later test's navigation with this test's stub.
  setNavigationGuard(null)
  window.history.pushState({}, '', '/')
})

describe('navigate, with no guard registered', () => {
  it('moves as it always did — the default state is "nothing to ask"', () => {
    navigate('/notes/NOTE-6')

    expect(window.location.pathname).toBe('/notes/NOTE-6')
  })
})

describe('navigate, with a guard registered', () => {
  it('proceeds when the guard allows it', () => {
    setNavigationGuard(() => true)

    navigate('/notes/NOTE-6')

    expect(window.location.pathname).toBe('/notes/NOTE-6')
  })

  it('does not move the URL when the guard refuses', () => {
    setNavigationGuard(() => false)

    navigate('/notes/NOTE-6')

    expect(window.location.pathname).toBe('/')
  })

  it('does not announce the vetoed route to subscribers either', () => {
    setNavigationGuard(() => false)
    const seen: string[] = []
    const unsubscribe = onNavigate((route) => seen.push(route.name))

    navigate('/notes/NOTE-6')

    expect(seen).toEqual([])
    unsubscribe()
  })

  it('is not consulted when navigating to the route already on screen', () => {
    // The same no-op `navigate` already had before this card: clicking the open note again pushes no
    // history entry, and it must not pop a dialog either — nothing is at risk because nothing moves.
    window.history.pushState({}, '', '/notes/NOTE-6')
    const guard = vi.fn(() => false)
    setNavigationGuard(guard)

    navigate('/notes/NOTE-6')

    expect(guard).not.toHaveBeenCalled()
  })

  it('is consulted again on the next navigation after a veto', () => {
    // A refused navigation must not disable the guard for the rest of the session — this is a repeated
    // question, not a one-shot confirmation.
    const guard = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true)
    setNavigationGuard(guard)

    navigate('/notes/NOTE-6')
    expect(window.location.pathname).toBe('/')

    navigate('/notes/NOTE-6')
    expect(window.location.pathname).toBe('/notes/NOTE-6')
    expect(guard).toHaveBeenCalledTimes(2)
  })

  it('stops being consulted once cleared', () => {
    setNavigationGuard(() => false)
    setNavigationGuard(null)

    navigate('/notes/NOTE-6')

    expect(window.location.pathname).toBe('/notes/NOTE-6')
  })
})

describe('interceptClick, through the same guard', () => {
  it('still calls preventDefault on a vetoed click, so the browser never navigates on its own either', () => {
    setNavigationGuard(() => false)
    const event = click()

    interceptClick(event, '/notes/NOTE-6')

    expect(event.preventDefault).toHaveBeenCalled()
    expect(window.location.pathname).toBe('/')
  })

  it('navigates once the guard allows it', () => {
    setNavigationGuard(() => true)
    const event = click()

    interceptClick(event, '/notes/NOTE-6')

    expect(window.location.pathname).toBe('/notes/NOTE-6')
  })

  it('never reaches the guard for a modified click — the browser handles that itself', () => {
    // `interceptClick` returns before `navigate` for these; a guard call here would mean this SPA
    // popped a confirmation for a click that was never going to touch its own history in the first
    // place.
    const guard = vi.fn(() => false)
    setNavigationGuard(guard)

    interceptClick(click({ metaKey: true }), '/notes/NOTE-6')
    interceptClick(click({ button: 1 }), '/notes/NOTE-6')

    expect(guard).not.toHaveBeenCalled()
  })
})
