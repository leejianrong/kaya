// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  READING_MEASURE_CH,
  readFullWidthReading,
  readingMeasure,
  watchFullWidthReading,
  writeFullWidthReading,
} from '../src/lib/preferences'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('the Read measure (KAN-1997)', () => {
  it('is ~75ch by default and none when full width is on', () => {
    expect(READING_MEASURE_CH).toBe(75)
    expect(readingMeasure(false)).toBe('75ch')
    expect(readingMeasure(true)).toBe('none')
  })

  it('defaults to capped, and remembers the choice', () => {
    expect(readFullWidthReading()).toBe(false)
    writeFullWidthReading(true)
    expect(readFullWidthReading()).toBe(true)
    writeFullWidthReading(false)
    expect(readFullWidthReading()).toBe(false)
  })

  it('tells subscribers on a write, and stops after unsubscribe', () => {
    const seen: boolean[] = []
    const stop = watchFullWidthReading((value) => seen.push(value))
    writeFullWidthReading(true)
    stop()
    writeFullWidthReading(false)
    expect(seen).toEqual([true])
  })

  it('falls back to the default when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readFullWidthReading()).toBe(false)
    const seen: boolean[] = []
    const stop = watchFullWidthReading((value) => seen.push(value))
    expect(() => writeFullWidthReading(true)).not.toThrow()
    stop()
    expect(seen).toEqual([true])
  })
})
