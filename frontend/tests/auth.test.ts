// @vitest-environment jsdom
/**
 * The credential seam, and the one rule with no exceptions: **the token never enters a URL, a log
 * line, an error message, or the DOM.**
 *
 * The fragment sweep below is `kaya-cli`'s `config show` lesson ported to the browser. Pandan
 * printed `set (…c_DE)` in a command documented as safe to paste, and those four characters are a
 * contiguous piece of a live credential; KAN-551 took it out and its tests now check every fragment
 * of four characters or more, in every format. Four rather than eight because the shape being
 * refused is a specific one — a mutation that leaked exactly four characters walked straight through
 * a six-character window.
 *
 * The fake credential and the sweep both come from `tests/token.ts`, which explains why it is spelled
 * the way the Python suites spell it.
 */

import { afterEach, describe, expect, it } from 'vitest'

import * as auth from '../src/lib/auth'
import { FAKE_TOKEN, fragments } from './token'

afterEach(() => {
  auth.clearToken()
})

describe('the credential seam', () => {
  it('round-trips a token through sessionStorage', () => {
    expect(auth.getToken()).toBeNull()
    auth.setToken(FAKE_TOKEN)
    expect(auth.getToken()).toBe(FAKE_TOKEN)
    expect(auth.hasToken()).toBe(true)
  })

  it('clears', () => {
    auth.setToken(FAKE_TOKEN)
    auth.clearToken()
    expect(auth.getToken()).toBeNull()
    expect(auth.hasToken()).toBe(false)
    expect(auth.authorization()).toBeNull()
  })

  it('stores in sessionStorage and never in localStorage', () => {
    // Not a style choice. The token is a *pandan* PAT (ADR 0002), so exfiltration hands over the
    // kanban board too, and KAN-554's preview will render user markdown to HTML in this origin.
    // `sessionStorage` dies with the tab; `localStorage` would outlive the browser.
    auth.setToken(FAKE_TOKEN)
    expect(Object.keys(localStorage)).toEqual([])
    expect(Object.keys(sessionStorage)).toContain('kaya.token')
  })

  it('builds a bearer header and nothing else', () => {
    auth.setToken(FAKE_TOKEN)
    expect(auth.authorization()).toBe(`Bearer ${FAKE_TOKEN}`)
  })

  it('refuses whitespace and control characters instead of storing them', () => {
    auth.setToken('   ')
    expect(auth.getToken()).toBeNull()

    // A `\r\n` in a header value is request splitting, and `fetch`'s TypeError can carry the value
    // it choked on. Refusing here keeps the token out of a stack trace.
    auth.setToken(`${FAKE_TOKEN}\r\nX-Injected: 1`)
    expect(auth.getToken()).toBeNull()
    expect(auth.isUsableToken(`${FAKE_TOKEN}\r\nX-Injected: 1`)).toBe(false)
    // A *trailing* newline is trimmed rather than refused — that is the paste case, not the
    // injection case, and refusing it would fail a correctly pasted token.
    expect(auth.isUsableToken(`${FAKE_TOKEN}\r\n`)).toBe(true)
  })

  it('trims a pasted token, because a paste form will produce whitespace', () => {
    auth.setToken(`  ${FAKE_TOKEN}\n`)
    expect(auth.getToken()).toBe(FAKE_TOKEN)
  })

  it('replacing a token with an unusable one clears rather than keeping the old one', () => {
    auth.setToken(FAKE_TOKEN)
    auth.setToken('')
    expect(auth.getToken()).toBeNull()
  })
})

describe('describing the credential', () => {
  it('says set or not set, and only that', () => {
    expect(auth.credentialState()).toBe('not set')
    auth.setToken(FAKE_TOKEN)
    expect(auth.credentialState()).toBe('set')
  })

  it('leaks no four-character fragment of the token through anything it describes', () => {
    auth.setToken(FAKE_TOKEN)

    const described = [
      auth.credentialState(),
      String(auth.hasToken()),
      String(auth.isUsableToken(FAKE_TOKEN)),
    ].join('|')

    for (const fragment of fragments(FAKE_TOKEN)) {
      expect(described).not.toContain(fragment)
    }
  })

  it('exposes no serializable state a stray log line could pick up', () => {
    auth.setToken(FAKE_TOKEN)

    // The module is functions only, so this is `{}` — and it must stay `{}`. An `export const
    // token`, a cached copy, or a getter added for convenience would all land in here, and
    // `console.log(auth)` in a debugging session is how it would reach a screen share.
    expect(JSON.stringify(auth)).toBe('{}')

    const surface = `${JSON.stringify(auth)}|${Object.keys(auth).join(',')}`
    for (const fragment of fragments(FAKE_TOKEN)) {
      expect(surface).not.toContain(fragment)
    }
  })
})
