import { describe, expect, it } from 'vitest'

import { API_BASE, apiPath } from '../src/lib/api'

describe('apiPath', () => {
  it('builds same-origin paths under the versioned prefix', () => {
    expect(apiPath('notes')).toBe('/api/v1/notes')
    expect(apiPath('/notes')).toBe('/api/v1/notes')
    expect(apiPath('notes/NOTE-1/backlinks')).toBe('/api/v1/notes/NOTE-1/backlinks')
  })

  it('returns the base itself for an empty path', () => {
    expect(apiPath('')).toBe(API_BASE)
    expect(apiPath('/')).toBe(API_BASE)
  })

  it('refuses an absolute URL', () => {
    // An absolute origin here would bypass the dev proxy and break the single-origin deploy,
    // and it would do so quietly — in dev, against a backend that happens to be running.
    expect(() => apiPath('http://localhost:8000/notes')).toThrow(/relative path/)
    expect(() => apiPath('//evil.example/notes')).toThrow(/relative path/)
  })

  it('never produces a path that leaves the api prefix', () => {
    for (const path of ['notes', '/notes', 'notes?q=x', 'notes/1']) {
      expect(apiPath(path).startsWith('/api/v1/')).toBe(true)
    }
  })
})
