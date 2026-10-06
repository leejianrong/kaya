// @vitest-environment jsdom
/**
 * KAN-1824: in Read mode a `[[wikilink]]` is a link when it resolves and a visibly different, inert
 * mark when it does not, and a body that opens with its own title does not show the title twice.
 *
 * `renderMarkdown` never fetches, so what it knows about resolution arrives as a plain array of the
 * `/links` rows the caller already holds. Both halves are pure and run here without a component.
 */

import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '../src/lib/markdown'
import { readingBody } from '../src/lib/readingBody'
import type { Link } from '../src/lib/types'

function render(source: string, links?: Link[]): HTMLDivElement {
  const holder = document.createElement('div')
  holder.append(renderMarkdown(source, { links }))
  return holder
}

const noteLink = (ref: string, target: string, title = target): Link => ({
  target_kind: 'NOTE',
  target_ref: target,
  resolved_ref: ref,
  title,
  column: null,
})

describe('a resolved note wikilink', () => {
  it('is an anchor to the note with no literal brackets', () => {
    const holder = render('See [[Roadmap]] today.', [noteLink('NOTE-4', 'Roadmap')])
    const anchor = holder.querySelector('a.wikilink')

    expect(anchor).not.toBeNull()
    expect(anchor!.getAttribute('href')).toBe('/notes/NOTE-4')
    expect(anchor!.textContent).toBe('Roadmap')
    expect(holder.textContent).toBe('See Roadmap today.')
    // In-app navigation: no new tab, so the router (and its unsaved-work guard) sees the click.
    expect(anchor!.getAttribute('target')).toBeNull()
  })

  it('refuses a resolved_ref that is not a NOTE ref', () => {
    const holder = render('[[Roadmap]]', [noteLink('javascript:alert(1)', 'Roadmap')])

    expect(holder.querySelector('a')).toBeNull()
    expect(holder.querySelector('.wikilink.unresolved')).not.toBeNull()
  })
})

describe('an unresolved wikilink', () => {
  it('is an inert, marked span with a hint and no brackets', () => {
    const holder = render('Try [[Nowhere]].', [])
    const mark = holder.querySelector('span.wikilink.unresolved')

    expect(holder.querySelector('a')).toBeNull()
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe('Nowhere')
    expect(mark!.getAttribute('title')).toContain('Nowhere')
    expect(mark!.getAttribute('role')).toBe('link')
    expect(mark!.getAttribute('aria-disabled')).toBe('true')
  })

  it('is what a link row with a null resolved_ref renders as', () => {
    const row: Link = { ...noteLink('NOTE-1', 'Gone'), resolved_ref: null, title: null }
    expect(render('[[Gone]]', [row]).querySelector('span.wikilink.unresolved')).not.toBeNull()
  })

  it('is what every wikilink renders as before /links has answered', () => {
    const holder = render('[[Roadmap]]', undefined)

    expect(holder.querySelector('a')).toBeNull()
    expect(holder.textContent).toBe('Roadmap')
    expect(holder.querySelector('span.wikilink.unresolved')).not.toBeNull()
  })
})

describe('a card or epic reference', () => {
  it('renders as a resolved chip, not a link, and never needs pandan', () => {
    const row: Link = {
      target_kind: 'KAN',
      target_ref: 'KAN-12',
      resolved_ref: 'KAN-12',
      title: 'Ship it',
      column: 'doing',
    }
    const holder = render('[[KAN-12]]', [row])
    const chip = holder.querySelector('span.wikilink.resolved')

    expect(holder.querySelector('a')).toBeNull()
    expect(chip!.textContent).toBe('KAN-12')
    expect(chip!.getAttribute('title')).toBe('KAN-12 · doing · "Ship it"')
  })

  it('degrades to unresolved when pandan did not answer', () => {
    const holder = render('[[EPIC-3]]', [])
    expect(holder.querySelector('span.wikilink.unresolved')!.textContent).toBe('EPIC-3')
  })
})

describe('what is not a wikilink', () => {
  it('leaves code alone', () => {
    const holder = render('`[[Roadmap]]`\n\n```\n[[Roadmap]]\n```', [noteLink('NOTE-4', 'Roadmap')])

    expect(holder.querySelector('.wikilink')).toBeNull()
    expect(holder.querySelector('code')!.textContent).toBe('[[Roadmap]]')
  })

  it('leaves a single-bracket link alone', () => {
    const holder = render('[a](https://example.com) and [b]', [noteLink('NOTE-4', 'b')])

    expect(holder.querySelector('.wikilink')).toBeNull()
  })

  it('handles several in one paragraph and keeps the surrounding text', () => {
    const holder = render('a [[One]] b [[Two]] c', [noteLink('NOTE-1', 'One')])

    expect(holder.textContent).toBe('a One b Two c')
    expect(holder.querySelectorAll('a.wikilink')).toHaveLength(1)
    expect(holder.querySelectorAll('span.wikilink.unresolved')).toHaveLength(1)
  })
})

describe('readingBody', () => {
  it('drops a leading H1 equal to the title', () => {
    expect(readingBody('# Roadmap\n\nText\n', 'Roadmap')).toBe('Text\n')
  })

  it('matches ignoring case, surrounding space and closing hashes', () => {
    expect(readingBody('#  roadmap ##\nText', 'Roadmap')).toBe('Text')
  })

  it('skips blank lines before the heading', () => {
    expect(readingBody('\n\n# Roadmap\nText', 'Roadmap')).toBe('Text')
  })

  it('keeps a heading that differs from the title', () => {
    const body = '# Week of 2026-08-03\n\nText'
    expect(readingBody(body, 'Weekly review')).toBe(body)
  })

  it('keeps an H2, a later H1 and an H1 after other text', () => {
    expect(readingBody('## Roadmap\nText', 'Roadmap')).toBe('## Roadmap\nText')
    expect(readingBody('Intro\n# Roadmap', 'Roadmap')).toBe('Intro\n# Roadmap')
  })

  it('keeps everything when the title is empty', () => {
    expect(readingBody('# \nText', '')).toBe('# \nText')
  })

  it('keeps a heading inside an opening fence', () => {
    const body = '```\n# Roadmap\n```'
    expect(readingBody(body, 'Roadmap')).toBe(body)
  })
})
