/**
 * KAN-1826: what each toolbar button does to a document and a selection, as pure functions.
 *
 * Fixtures write the selection inline so a case reads as before and after: `|` is a caret, and
 * `{` `}` bracket a selected range. `apply` returns the same notation, so an expectation is the
 * document the person would see, caret included.
 */
import { describe, expect, it } from 'vitest'

import { type FormatAction, applyFormat, isUrl } from '../src/lib/formatting'

function parse(marked: string): { doc: string; anchor: number; head: number } {
  const caret = marked.indexOf('|')
  if (caret !== -1) {
    const doc = marked.slice(0, caret) + marked.slice(caret + 1)
    return { doc, anchor: caret, head: caret }
  }
  const open = marked.indexOf('{')
  const close = marked.indexOf('}')
  const doc = marked.slice(0, open) + marked.slice(open + 1, close) + marked.slice(close + 1)
  return { doc, anchor: open, head: close - 1 }
}

function show(doc: string, anchor: number, head: number): string {
  if (anchor === head) {
    return `${doc.slice(0, anchor)}|${doc.slice(anchor)}`
  }
  const from = Math.min(anchor, head)
  const to = Math.max(anchor, head)
  return `${doc.slice(0, from)}{${doc.slice(from, to)}}${doc.slice(to)}`
}

function apply(action: FormatAction, marked: string): string {
  const { doc, anchor, head } = parse(marked)
  const edit = applyFormat(action, doc, { anchor, head })
  expect(edit).not.toBeNull()
  const next = doc.slice(0, edit!.from) + edit!.insert + doc.slice(edit!.to)
  return show(next, edit!.anchor, edit!.head)
}

describe('bold', () => {
  it('wraps a selection and keeps it selected', () => {
    expect(apply('bold', 'a {word} here')).toBe('a **{word}** here')
  })

  it('unwraps when the marks sit just outside the selection', () => {
    expect(apply('bold', 'a **{word}** here')).toBe('a {word} here')
  })

  it('unwraps when the selection includes the marks', () => {
    expect(apply('bold', 'a {**word**} here')).toBe('a {word} here')
  })

  it('opens an empty pair at a bare caret between spaces', () => {
    expect(apply('bold', 'a | b')).toBe('a **|** b')
  })

  it('removes an empty pair the caret sits in', () => {
    expect(apply('bold', 'a **|** b')).toBe('a | b')
  })

  it('wraps the word under a caret and keeps the caret in place', () => {
    expect(apply('bold', 'a wo|rd here')).toBe('a **wo|rd** here')
  })

  it('unwraps the word under a caret', () => {
    expect(apply('bold', 'a **wo|rd** here')).toBe('a wo|rd here')
  })

  it('does not treat italic marks as bold', () => {
    expect(apply('bold', 'a *{word}* here')).toBe('a ***{word}*** here')
  })
})

describe('italic', () => {
  it('wraps and unwraps with single asterisks', () => {
    expect(apply('italic', 'a {word}')).toBe('a *{word}*')
    expect(apply('italic', 'a *{word}*')).toBe('a {word}')
  })

  it('does not unwrap bold, it adds italic on top', () => {
    expect(apply('italic', 'a **{word}**')).toBe('a ***{word}***')
  })

  it('removes only the italic layer from bold italic', () => {
    expect(apply('italic', 'a ***{word}***')).toBe('a **{word}**')
  })
})

describe('code', () => {
  it('wraps a selection in backticks and toggles back', () => {
    expect(apply('code', 'run {npm test} now')).toBe('run `{npm test}` now')
    expect(apply('code', 'run `{npm test}` now')).toBe('run {npm test} now')
  })

  it('opens an empty pair with the caret inside', () => {
    expect(apply('code', 'run | now')).toBe('run `|` now')
  })

  it('fences a selection that spans lines', () => {
    expect(apply('code', '{one\ntwo}')).toBe('```\n{one\ntwo}\n```')
  })
})

describe('list', () => {
  it('adds a bullet to the caret line', () => {
    expect(apply('list', 'item| one')).toBe('- item| one')
  })

  it('removes the bullet when the line has one', () => {
    expect(apply('list', '- item| one')).toBe('item| one')
  })

  it('bullets every selected line and skips blank ones', () => {
    expect(apply('list', '{one\n\ntwo}')).toBe('- {one\n\n- two}')
  })

  it('removes bullets only when every line has one', () => {
    expect(apply('list', '{- one\n- two}')).toBe('{one\ntwo}')
    expect(apply('list', '{- one\ntwo}')).toBe('{- one\n- two}')
  })

  it('keeps indentation', () => {
    expect(apply('list', '  nested|')).toBe('  - nested|')
  })

  it('turns a checkbox line into a plain bullet', () => {
    expect(apply('list', '- [ ] task|')).toBe('- task|')
  })

  it('works on an empty line', () => {
    expect(apply('list', '|')).toBe('- |')
  })
})

describe('checkbox', () => {
  it('adds a checkbox to a plain line', () => {
    expect(apply('checkbox', 'task|')).toBe('- [ ] task|')
  })

  it('turns a bullet into a checkbox', () => {
    expect(apply('checkbox', '- task|')).toBe('- [ ] task|')
  })

  it('removes the checkbox and the bullet together, checked or not', () => {
    expect(apply('checkbox', '- [ ] task|')).toBe('task|')
    expect(apply('checkbox', '- [x] task|')).toBe('task|')
  })

  it('handles several lines', () => {
    expect(apply('checkbox', '{a\nb}')).toBe('- [ ] {a\n- [ ] b}')
  })
})

describe('link', () => {
  it('wraps the selection and puts the caret in the empty address', () => {
    expect(apply('link', 'see {the docs}')).toBe('see [the docs](|)')
  })

  it('puts the caret in the text when there is no selection', () => {
    expect(apply('link', 'see |')).toBe('see [|]()')
  })

  it('uses a selected address as the address and leaves the caret in the text', () => {
    expect(apply('link', 'see {https://example.com/a}')).toBe('see [|](https://example.com/a)')
  })
})

describe('wikilink', () => {
  it('wraps a selection in [[ ]] and puts the caret after it', () => {
    expect(apply('wikilink', 'see {Retro notes} now')).toBe('see [[Retro notes]]| now')
  })

  it('types only [[ at a bare caret, so the title completion finishes the link', () => {
    const { doc, anchor, head } = parse('see |')
    const edit = applyFormat('wikilink', doc, { anchor, head })
    expect(edit).toMatchObject({ insert: '[[', opensWikilinkCompletion: true })
    expect(apply('wikilink', 'see |')).toBe('see [[|')
  })

  it('does not open completion when it wrapped a selection', () => {
    const { doc, anchor, head } = parse('{Retro}')
    expect(applyFormat('wikilink', doc, { anchor, head })?.opensWikilinkCompletion).toBe(false)
  })

  it('unwraps a selection that is already a wikilink', () => {
    expect(apply('wikilink', 'see {[[Retro]]}')).toBe('see {Retro}')
  })
})

describe('selection direction', () => {
  it('accepts a backwards selection', () => {
    const edit = applyFormat('bold', 'word', { anchor: 4, head: 0 })
    expect(edit?.insert).toBe('**word**')
  })
})

describe('isUrl', () => {
  it('accepts http and https addresses only', () => {
    expect(isUrl('https://a.b/c')).toBe(true)
    expect(isUrl('http://a.b')).toBe(true)
    expect(isUrl('a.b')).toBe(false)
    expect(isUrl('https://a b')).toBe(false)
  })
})
