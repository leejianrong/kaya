import { describe, expect, it } from 'vitest'

import { parseScope, presetFor, TOKEN_PRESETS } from '../src/lib/tokenPresets'

describe('token presets', () => {
  it('lists full access first, the default for a new token', () => {
    expect(TOKEN_PRESETS.map((preset) => preset.scope)).toEqual(['write', 'write-no-delete', 'read'])
  })

  it('gives every preset a label and a one-line explanation', () => {
    for (const preset of TOKEN_PRESETS) {
      expect(preset.label).not.toBe('')
      expect(preset.description).toMatch(/\.$/)
    }
  })

  it('shows an unknown scope as itself rather than hiding it', () => {
    expect(presetFor('write-no-move').label).toBe('write-no-move')
  })

  it('parses a query scope, defaulting to write', () => {
    expect(parseScope('write-no-delete')).toBe('write-no-delete')
    expect(parseScope('read')).toBe('read')
    expect(parseScope('bogus')).toBe('write')
    expect(parseScope(null)).toBe('write')
  })
})
