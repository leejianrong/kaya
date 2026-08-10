// @vitest-environment jsdom
/**
 * `lib/markdown.ts` — the renderer, and the one place in kaya where an attacker's bytes are rendered
 * as markup.
 *
 * KAN-555 put the credential in `sessionStorage` rather than `localStorage` **because of this file's
 * subject**: a live pandan PAT sits in the same origin as a preview of user-controlled markdown. So
 * the security half below is written as a **property over a battery of payloads** rather than as one
 * assertion per attack:
 *
 * - every element in the output has an allow-listed tag name,
 * - every attribute has an allow-listed name — which is the assertion that covers `onerror`,
 *   `onload`, `onmouseover` and every event handler nobody has thought of, because they are all
 *   attributes and none of them is on the list,
 * - no attribute value carries a scheme outside `http`/`https`/`mailto`.
 *
 * A per-payload test only ever refuses the payloads someone wrote down. The named tests after the
 * battery exist as well, because a property that passes for the wrong reason (nothing rendered at
 * all) needs a witness that the *text* survived — an inert preview and an empty preview are not the
 * same thing, and only one of them is correct.
 */

import { describe, expect, it } from 'vitest'

import { renderMarkdown, safeUrl } from '../src/lib/markdown'

/** Every tag `lib/markdown.ts` is allowed to create. Each one is a literal in that file. */
const ALLOWED_TAGS = new Set([
  'a',
  'blockquote',
  'br',
  'code',
  'del',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'hr',
  'img',
  'input',
  'li',
  'ol',
  'p',
  'pre',
  'strong',
  'sub',
  'sup',
  'table',
  'tbody',
  'td',
  'th',
  'thead',
  'tr',
  'ul',
])

/**
 * Every attribute name it is allowed to set.
 *
 * `class` is on it because two elements carry one this file chose (`raw-html`, `task`); `type`,
 * `disabled` and `checked` are the task checkbox. Nothing source-derived is here except the two URL
 * slots and `alt`.
 */
const ALLOWED_ATTRIBUTES = new Set([
  'alt',
  'checked',
  'class',
  'disabled',
  'href',
  'loading',
  'referrerpolicy',
  'rel',
  'src',
  'start',
  'target',
  'type',
])

/** Schemes that must never reach an attribute value. */
const FORBIDDEN_SCHEMES = /^\s*(javascript|data|vbscript|file|blob)\s*:/i

interface Finding {
  tags: string[]
  attributes: string[]
  values: string[]
}

/** Everything the property cares about, collected in one walk so a failure names all of it. */
function inspect(source: string): Finding {
  const fragment = renderMarkdown(source)
  const tags: string[] = []
  const attributes: string[] = []
  const values: string[] = []

  for (const element of fragment.querySelectorAll('*')) {
    tags.push(element.tagName.toLowerCase())
    for (const attribute of element.attributes) {
      attributes.push(attribute.name.toLowerCase())
      if (FORBIDDEN_SCHEMES.test(attribute.value)) {
        values.push(`${attribute.name}=${attribute.value}`)
      }
    }
  }
  return { tags, attributes, values }
}

function text(source: string): string {
  const holder = document.createElement('div')
  holder.append(renderMarkdown(source))
  return holder.textContent ?? ''
}

function html(source: string): string {
  const holder = document.createElement('div')
  holder.append(renderMarkdown(source))
  return holder.innerHTML
}

/**
 * The payloads. Real ones, not sketches.
 *
 * The four the card names are here (`<script>`, `onerror=`, a `javascript:` URL, an `<iframe>`) plus
 * the variants that defeat a naive filter: a scheme with a control character in it, one with mixed
 * case, an entity-encoded script tag, `srcdoc`, an SVG `onload`, a `data:text/html` document, and a
 * `<style>` block.
 */
const PAYLOADS: Record<string, string> = {
  'raw script tag': '<script>alert(document.domain)</script>',
  'inline script tag': 'text <script>alert(1)</script> more',
  'img with onerror': '<img src=x onerror="alert(document.domain)">',
  'svg with onload': '<svg onload=alert(1)></svg>',
  iframe: '<iframe src="https://evil.example.com"></iframe>',
  'iframe with srcdoc': '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
  'javascript link': '[click me](javascript:alert(document.domain))',
  'javascript link mixed case': '[click me](JaVaScRiPt:alert(1))',
  'javascript link with a tab': '[click me](java\tscript:alert(1))',
  'javascript link with a newline': '[click me](java\nscript:alert(1))',
  'javascript autolink': '<javascript:alert(1)>',
  'data url link': '[click](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)',
  'javascript image': '![x](javascript:alert(1))',
  'data url image': '![x](data:text/html,<script>alert(1)</script>)',
  'reference link to javascript': '[click][evil]\n\n[evil]: javascript:alert(1)',
  'entity encoded script': '&lt;script&gt;alert(1)&lt;/script&gt;',
  'style block': '<style>body { display: none }</style>',
  'html comment with markup': '<!-- <script>alert(1)</script> -->',
  'anchor with a handler': '<a href="#" onclick="alert(1)">x</a>',
  'body onload': '<body onload=alert(1)>',
  'form action': '<form action="https://evil.example.com"><input name="p"></form>',
  'base tag': '<base href="https://evil.example.com/">',
  'meta refresh': '<meta http-equiv="refresh" content="0;url=https://evil.example.com">',
  'nested in a blockquote': '> <img src=x onerror=alert(1)>',
  'nested in a list': '- <script>alert(1)</script>',
  'nested in a table cell': '| a |\n|---|\n| <img src=x onerror=alert(1)> |',
  'nested in a link label': '[<img src=x onerror=alert(1)>](https://ok.example.com)',
  'nested in emphasis': '*<script>alert(1)</script>*',
  'inside a fenced block': '```\n<script>alert(1)</script>\n```',
}

describe('the rendered output can only contain what this repo named', () => {
  for (const [name, payload] of Object.entries(PAYLOADS)) {
    it(`refuses to build markup from: ${name}`, () => {
      const { tags, attributes, values } = inspect(payload)

      // The three properties. `toEqual([])` on the difference rather than a `not.toContain` per
      // attack, so the failure message names the tag or attribute that got through.
      expect(tags.filter((tag) => !ALLOWED_TAGS.has(tag))).toEqual([])
      expect(attributes.filter((attribute) => !ALLOWED_ATTRIBUTES.has(attribute))).toEqual([])
      expect(values).toEqual([])
    })
  }

  it('never emits a script, iframe, style, object, embed, form or svg element for any payload', () => {
    // The named half of the property above. A reader looking for "is `<script>` handled?" should find
    // the word, and `ALLOWED_TAGS` is a list they would have to reason about to answer.
    for (const payload of Object.values(PAYLOADS)) {
      const fragment = renderMarkdown(payload)
      expect(
        fragment.querySelectorAll('script, iframe, style, object, embed, form, svg, base, meta, link'),
      ).toHaveLength(0)
    }
  })

  it('never emits an attribute starting with `on`, for any payload', () => {
    for (const payload of Object.values(PAYLOADS)) {
      const fragment = renderMarkdown(payload)
      for (const element of fragment.querySelectorAll('*')) {
        for (const attribute of element.attributes) {
          expect(attribute.name.toLowerCase().startsWith('on')).toBe(false)
        }
      }
    }
  })
})

describe('inert is not the same as gone', () => {
  it('shows a raw script tag as visible text, character for character', () => {
    // The witness for the property above. A renderer that dropped every payload would pass the
    // battery and lose the note's content, which is the other failure this card can produce.
    const source = '<script>alert(1)</script>'
    expect(text(source)).toContain(source)
    expect(html(source)).not.toContain('<script')
  })

  it('shows an inline `onerror` payload as text inside a paragraph', () => {
    const source = 'before <img src=x onerror=alert(1)> after'
    const holder = document.createElement('div')
    holder.append(renderMarkdown(source))

    // Every character survives — as characters. The string `onerror=` is *in* the markup, escaped,
    // which is the correct outcome and the reason this asserts over the DOM rather than over the
    // serialized HTML: what matters is that no element carries the attribute and no `img` exists.
    expect(holder.textContent).toBe(source)
    expect(holder.querySelector('img')).toBeNull()
    expect(holder.querySelector('[onerror]')).toBeNull()
    expect(html(source)).toContain('&lt;img')
  })

  it('labels a raw HTML block so a reader knows it was not rendered', () => {
    const fragment = renderMarkdown('<div>hello</div>')
    const block = fragment.querySelector('pre.raw-html')

    expect(block).not.toBeNull()
    expect(block?.textContent).toBe('<div>hello</div>')
  })

  it('decodes an entity-encoded script into text and not into markup', () => {
    // `&lt;script&gt;` decodes to a string starting with `<`. It ends up in a `Text` node, so it is
    // one visible character — that is why decoding cannot be an injection bug here.
    const rendered = renderMarkdown('&lt;script&gt;alert(1)&lt;/script&gt;')
    const holder = document.createElement('div')
    holder.append(rendered)

    expect(holder.textContent).toBe('<script>alert(1)</script>')
    expect(holder.querySelector('script')).toBeNull()
  })

  it('keeps the words of a link it refuses to make clickable', () => {
    const fragment = renderMarkdown('[click me](javascript:alert(1))')
    const holder = document.createElement('div')
    holder.append(fragment)

    expect(holder.textContent).toContain('click me')
    expect(holder.querySelector('a')).toBeNull()
  })

  it('shows the source of an image it refuses, rather than a broken element', () => {
    const fragment = renderMarkdown('![alt](javascript:alert(1))')
    const holder = document.createElement('div')
    holder.append(fragment)

    expect(holder.querySelector('img')).toBeNull()
    expect(holder.textContent).toContain('![alt](javascript:alert(1))')
  })
})

describe('safeUrl', () => {
  it('accepts the three schemes a preview may link to', () => {
    expect(safeUrl('https://example.com/a?b=c#d')).toBe('https://example.com/a?b=c#d')
    expect(safeUrl('http://example.com/')).toBe('http://example.com/')
    expect(safeUrl('mailto:someone@example.com')).toBe('mailto:someone@example.com')
  })

  it('refuses every other scheme, in any casing, with any padding', () => {
    for (const raw of [
      'javascript:alert(1)',
      'JAVASCRIPT:alert(1)',
      '  javascript:alert(1)  ',
      'vbscript:msgbox(1)',
      'data:text/html,<script>alert(1)</script>',
      'file:///etc/passwd',
      'blob:https://example.com/x',
    ]) {
      expect(safeUrl(raw)).toBeNull()
    }
  })

  it('refuses a scheme smuggled past a parser by a control character', () => {
    // `new URL()` strips tab, newline and carriage return per the URL spec, so these *would* parse as
    // `javascript:`. Refusing the bytes before parsing means the allow-list never has to reason about
    // what the parser silently removed.
    for (const raw of ['java\tscript:alert(1)', 'java\nscript:alert(1)', 'java\rscript:alert(1)']) {
      expect(safeUrl(raw)).toBeNull()
    }
  })

  it('refuses a relative or fragment-only target rather than inventing a base', () => {
    // Wikilinks are KAN-567 and there is no resolver yet, so a relative target has no destination
    // this renderer can honestly claim.
    for (const raw of ['other-note.md', '/notes/NOTE-4', '#heading', '', '   ']) {
      expect(safeUrl(raw)).toBeNull()
    }
  })
})

describe('links that are rendered', () => {
  it('opens in a new tab with `noopener noreferrer`, and says why in the source', () => {
    const anchor = renderMarkdown('[kaya](https://example.com/x)').querySelector('a')

    expect(anchor?.getAttribute('href')).toBe('https://example.com/x')
    // `target=_blank` so a click does not navigate away from an editor holding unsaved work;
    // `noopener` so the opened page gets no handle back into the origin holding the PAT;
    // `noreferrer` so the note's URL — which carries a `NOTE-n` ref — is not leaked.
    expect(anchor?.getAttribute('target')).toBe('_blank')
    expect(anchor?.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('renders inline markup inside a link label without leaking the URL into the text', () => {
    const anchor = renderMarkdown('[**bold** text](https://example.com/)').querySelector('a')

    expect(anchor?.querySelector('strong')?.textContent).toBe('bold')
    expect(anchor?.textContent).toBe('bold text')
  })

  it('resolves a reference link against its definition', () => {
    const fragment = renderMarkdown('see [the docs][d]\n\n[d]: https://example.com/docs')

    expect(fragment.querySelector('a')?.getAttribute('href')).toBe('https://example.com/docs')
    // The definition block itself is not rendered, which is CommonMark's own behaviour.
    expect(fragment.textContent).not.toContain('[d]:')
  })

  it('keeps an image out of the referrer and off the critical path', () => {
    const image = renderMarkdown('![a cat](https://example.com/cat.png)').querySelector('img')

    expect(image?.getAttribute('src')).toBe('https://example.com/cat.png')
    expect(image?.getAttribute('alt')).toBe('a cat')
    expect(image?.getAttribute('referrerpolicy')).toBe('no-referrer')
    expect(image?.getAttribute('loading')).toBe('lazy')
  })
})

describe('the markdown a note actually contains', () => {
  it('renders headings at the right level, ATX and setext alike', () => {
    expect(renderMarkdown('# a').querySelector('h1')?.textContent).toBe('a')
    expect(renderMarkdown('###### f').querySelector('h6')?.textContent).toBe('f')
    expect(renderMarkdown('a\n===').querySelector('h1')?.textContent).toBe('a')
    expect(renderMarkdown('a\n---').querySelector('h2')?.textContent).toBe('a')
  })

  it('renders emphasis, strong, strikethrough and inline code', () => {
    const fragment = renderMarkdown('*a* **b** ~~c~~ `d`')

    expect(fragment.querySelector('em')?.textContent).toBe('a')
    expect(fragment.querySelector('strong')?.textContent).toBe('b')
    expect(fragment.querySelector('del')?.textContent).toBe('c')
    expect(fragment.querySelector('code')?.textContent).toBe('d')
  })

  it('renders nested lists, keeping the nesting', () => {
    const fragment = renderMarkdown('- a\n- b\n  - deep\n')
    const outer = fragment.querySelector('ul')

    expect(outer?.querySelectorAll(':scope > li')).toHaveLength(2)
    expect(outer?.querySelector('li ul li')?.textContent).toBe('deep')
  })

  it('renders an ordered list that starts somewhere other than 1', () => {
    expect(renderMarkdown('3. c\n4. d').querySelector('ol')?.getAttribute('start')).toBe('3')
    expect(renderMarkdown('1. a\n2. b').querySelector('ol')?.getAttribute('start')).toBeNull()
  })

  it('renders a GFM task list as disabled checkboxes reflecting the marker', () => {
    const boxes = renderMarkdown('- [ ] open\n- [x] done').querySelectorAll('input')

    expect(boxes).toHaveLength(2)
    expect((boxes[0] as HTMLInputElement).checked).toBe(false)
    expect((boxes[1] as HTMLInputElement).checked).toBe(true)
    expect((boxes[0] as HTMLInputElement).disabled).toBe(true)
  })

  it('renders a fenced block as code, verbatim, without a language class', () => {
    const code = renderMarkdown('```js\nconst x = 1 < 2\n```').querySelector('pre code')

    expect(code?.textContent).toBe('const x = 1 < 2')
    expect(code?.getAttribute('class')).toBeNull()
  })

  it('renders a blockquote without its quote marks', () => {
    // Normalised, because a continuation line's `> ` leaves a space the renderer keeps verbatim and
    // HTML collapses. Asserting the un-normalised string would pin that whitespace as a contract.
    const quote = renderMarkdown('> quoted\n> lines').querySelector('blockquote p')

    expect(quote?.textContent?.replace(/\s+/g, ' ')).toBe('quoted lines')
    expect(quote?.textContent).not.toContain('>')
  })

  it('renders a GFM table with a header row', () => {
    const table = renderMarkdown('| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |').querySelector('table')

    expect(Array.from(table?.querySelectorAll('thead th') ?? []).map((c) => c.textContent)).toEqual([
      'a',
      'b',
    ])
    expect(table?.querySelectorAll('tbody tr')).toHaveLength(2)
  })

  it('renders a hard break and a horizontal rule', () => {
    expect(renderMarkdown('a  \nb').querySelector('br')).not.toBeNull()
    expect(renderMarkdown('---').querySelector('hr')).not.toBeNull()
  })

  it('shows an escaped character as itself', () => {
    expect(text('\\*not emphasis\\*')).toBe('*not emphasis*')
  })

  it('leaves an emoji shortcode alone rather than dropping it', () => {
    // No shortcode table (see the module header). The failure to refuse is *losing* the text, which
    // the unknown-node fallback is written to prevent.
    expect(text('hi :smile: there')).toBe('hi :smile: there')
  })

  it('renders an empty document as nothing at all', () => {
    expect(renderMarkdown('').childNodes).toHaveLength(0)
  })
})
