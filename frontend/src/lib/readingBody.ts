/**
 * KAN-1824: the markdown Read mode renders, which is the stored body minus a leading heading that
 * only repeats the note's title.
 *
 * Read mode shows the title as the document's heading already, so a body that opens with
 * `# <the same title>` would print it twice. The rule is deliberately narrow: the first non-blank
 * line must be an ATX level-one heading whose text equals the title once case, surrounding space and
 * closing `#` marks are ignored. A different heading, a level-two heading, a heading that follows
 * other text and a heading inside a fence are all content and stay.
 *
 * This only shapes what is rendered. The stored body, the editor and every save are untouched.
 */

const LEADING_H1 = /^(?:[ \t]*\r?\n)*#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*(?:\r?\n|$)/

function same(a: string, b: string): boolean {
  const fold = (text: string): string => text.trim().replace(/\s+/g, ' ').toLowerCase()
  return fold(a) === fold(b)
}

export function readingBody(body: string, title: string): string {
  if (title.trim() === '') {
    return body
  }
  const match = LEADING_H1.exec(body)
  if (match === null || !same(match[1], title)) {
    return body
  }
  // The blank lines that separated the heading from the text go with it.
  return body.slice(match[0].length).replace(/^(?:[ \t]*\r?\n)+/, '')
}
