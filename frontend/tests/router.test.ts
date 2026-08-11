/**
 * The router is two routes and a hand-written parser, so it gets assertions rather than trust.
 *
 * A router library would have arrived with its own test suite; the price of not adding one for two
 * routes (`lib/router.ts` explains why) is writing the tests it would have brought. The failure
 * mode this covers is quiet: a deep link that parses to `unknown` shows an empty pane rather than
 * an error, and `spa.py` has already returned a `200` for it.
 */

import { describe, expect, it } from 'vitest'

import { parseRoute, routeHref } from '../src/lib/router'

describe('parseRoute', () => {
  it('reads / as home', () => {
    expect(parseRoute('/')).toEqual({ name: 'home' })
    expect(parseRoute('')).toEqual({ name: 'home' })
  })

  it('reads /notes/NOTE-12 as that ref', () => {
    expect(parseRoute('/notes/NOTE-12')).toEqual({ name: 'note', ref: 'NOTE-12' })
  })

  it('passes every spelling the backend accepts straight through', () => {
    // `app/api/refs.py` is the single place an identifier is parsed, and it takes all three. A
    // second grammar here would either reject something the API accepts or accept something it
    // rejects; both are bugs whose fix is deleting the copy.
    expect(parseRoute('/notes/note-12')).toEqual({ name: 'note', ref: 'note-12' })
    expect(parseRoute('/notes/12')).toEqual({ name: 'note', ref: '12' })
  })

  it('leaves a malformed ref for the backend to refuse', () => {
    // `#NOTE-12` is a documented `400` (ADR 0008). It only gets one if the client forwards it.
    expect(parseRoute('/notes/%23NOTE-12')).toEqual({ name: 'note', ref: '#NOTE-12' })
    expect(parseRoute('/notes/nonsense')).toEqual({ name: 'note', ref: 'nonsense' })
  })

  it('ignores the query and the fragment', () => {
    expect(parseRoute('/notes/NOTE-3?edit=1')).toEqual({ name: 'note', ref: 'NOTE-3' })
    expect(parseRoute('/notes/NOTE-3#heading')).toEqual({ name: 'note', ref: 'NOTE-3' })
    expect(parseRoute('/?x=1')).toEqual({ name: 'home' })
  })

  it('tolerates a trailing slash rather than routing it somewhere else', () => {
    expect(parseRoute('/notes/NOTE-3/')).toEqual({ name: 'note', ref: 'NOTE-3' })
  })

  it('names an unknown path instead of silently redirecting home', () => {
    // A stale or mistyped link should say what was asked for. Rewriting the URL to `/` loses the
    // evidence, and `spa.py` served a 200 for it, so nothing else will report it.
    expect(parseRoute('/nonesuch')).toEqual({ name: 'unknown', path: '/nonesuch' })
    expect(parseRoute('/notes')).toEqual({ name: 'unknown', path: '/notes' })
    expect(parseRoute('/notes/')).toEqual({ name: 'unknown', path: '/notes' })
    expect(parseRoute('/notes/NOTE-3/extra')).toEqual({
      name: 'unknown',
      path: '/notes/NOTE-3/extra',
    })
  })

  it('survives a malformed percent escape', () => {
    // `decodeURIComponent('%')` throws, and a thrown parse is a blank page.
    expect(() => parseRoute('/notes/%')).not.toThrow()
    expect(parseRoute('/notes/%')).toEqual({ name: 'note', ref: '%' })
  })
})

describe('routeHref', () => {
  it('round-trips the two real routes', () => {
    for (const path of ['/', '/notes/NOTE-12', '/notes/12']) {
      expect(routeHref(parseRoute(path))).toBe(path)
    }
  })

  it('encodes a ref as one segment', () => {
    // A `/` inside a ref must address a 404, not a different route.
    expect(routeHref({ name: 'note', ref: 'a/b' })).toBe('/notes/a%2Fb')
  })
})
