/**
 * `lib/preferences.ts` and the two pure helpers the format-on-save path rests on (KAN-1815).
 * Node environment: nothing here needs a DOM.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { minimalChange, needsDispatch, syncFormatted } from '../src/lib/editor'
import {
  DEFAULT_FORMAT_ON_SAVE,
  formatOnSave,
  primePreferences,
  rememberFormatOnSave,
  resetPreferencesCache,
} from '../src/lib/preferences'

describe('formatOnSave', () => {
  let reads: number
  let answer: () => Response

  beforeEach(() => {
    resetPreferencesCache()
    reads = 0
    answer = () => new Response(JSON.stringify({ format_on_save: false }), { status: 200 })
    vi.stubGlobal('fetch', async () => {
      reads += 1
      return answer()
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('defaults to ON', () => {
    expect(DEFAULT_FORMAT_ON_SAVE).toBe(true)
  })

  it("answers the account's stored choice, read once however often it is asked", async () => {
    expect(await formatOnSave()).toBe(false)
    expect(await formatOnSave()).toBe(false)
    await primePreferences()

    expect(reads).toBe(1)
  })

  it('answers ON when the read fails, and retries rather than caching the failure', async () => {
    answer = () => new Response('{}', { status: 500 })
    expect(await formatOnSave()).toBe(true)

    answer = () => new Response(JSON.stringify({ format_on_save: false }), { status: 200 })
    expect(await formatOnSave()).toBe(false)
    expect(reads).toBe(2)
  })

  it('answers ON for a payload that is not the preferences shape', async () => {
    answer = () => new Response(JSON.stringify({ title: 'a note' }), { status: 200 })

    expect(await formatOnSave()).toBe(true)
  })

  it('is written through by the Settings page, with no further read', async () => {
    rememberFormatOnSave(false)

    expect(await formatOnSave()).toBe(false)
    expect(reads).toBe(0)
  })
})

describe('minimalChange', () => {
  function apply(before: string, change: { from: number; to: number; insert: string }): string {
    return before.slice(0, change.from) + change.insert + before.slice(change.to)
  }

  it.each([
    ['identical', 'same\n', 'same\n'],
    ['insert in the middle', 'ab', 'aXb'],
    ['delete in the middle', 'aXb', 'ab'],
    ['replace', '*  one\n', '- one\n'],
    ['grow at the end', '# T', '# T\n'],
    ['repeated characters', 'aaa', 'aaaa'],
    ['empty before', '', 'x'],
    ['empty after', 'x', ''],
    ['totally different', 'abc', 'xyz'],
  ])('produces a change that turns before into after: %s', (_name, before, after) => {
    expect(apply(before, minimalChange(before, after))).toBe(after)
  })

  it('spans only what differs', () => {
    expect(minimalChange('keep\n*  x\nkeep\n', 'keep\n- x\nkeep\n')).toEqual({
      from: 5,
      to: 7,
      insert: '-',
    })
  })
})

describe('syncFormatted', () => {
  function stubView(doc: string) {
    const dispatch = vi.fn()
    return {
      view: { state: { doc: { toString: () => doc, length: doc.length } }, dispatch } as never,
      dispatch,
    }
  }

  it('dispatches nothing when the stored body is already what the editor holds (the echo guard)', () => {
    const { view, dispatch } = stubView('same\n')

    expect(syncFormatted(view, 'same\n', 'same\n')).toBe(false)
    expect(needsDispatch('same\n', 'same\n')).toBe(false)
    expect(dispatch).not.toHaveBeenCalled()
  })

  it('dispatches one minimal transaction for a formatted body', () => {
    const { view, dispatch } = stubView('*  x\n')

    expect(syncFormatted(view, '*  x\n', '- x\n')).toBe(true)
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(dispatch.mock.calls[0][0].changes).toEqual({ from: 0, to: 2, insert: '-' })
  })

  it('refuses to touch a document typed into since the save was sent', () => {
    const { view, dispatch } = stubView('*  x\nand more')

    expect(syncFormatted(view, '*  x\n', '- x\n')).toBe(false)
    expect(dispatch).not.toHaveBeenCalled()
  })
})
