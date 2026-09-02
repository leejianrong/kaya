// @vitest-environment jsdom
/**
 * R14's drop/paste-to-upload handler (KAN-1067), against a real `EditorView` — the same posture
 * `codemirror-wikilinks.test.ts` takes for the pill and `[[` autocomplete: dispatched through
 * `createView`'s real extension set, not a reach into a private helper.
 *
 * `lib/attachments.ts` is mocked (`vi.mock`, hoisted above the imports below by vitest) rather than
 * given a fake `fetch`: this file is about the CM6-side wiring — which file gets picked out of the
 * event, where the placeholder lands, how it resolves — and that is a separate question from
 * `tests/attachments.test.ts`'s, which already covers `uploadAttachment`'s own request shape and
 * error handling in full.
 *
 * jsdom in this project's test environment implements neither `DragEvent` nor `ClipboardEvent`
 * (checked directly against `globalThis` — both are `undefined`), so a `drop`/`paste` is simulated
 * with a plain `Event` carrying the two properties `lib/codemirror.ts`'s handlers actually read
 * (`dataTransfer`/`clipboardData`, and `clientX`/`clientY` for drop), dispatched on
 * `view.contentDOM` — CM6's `InputState` listens there rather than on `view.dom` (verified against
 * `@codemirror/view`'s own source, `ensureHandlers`). `handleEvent`/`runHandlers` dispatch by
 * `event.type` alone, agnostic to which `Event` subclass fired, so this reaches the real handler
 * rather than a stand-in for it.
 */

import { EditorView } from '@codemirror/view'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/lib/attachments', () => ({
  uploadAttachment: vi.fn(),
}))

import { createView, type EditorSpec } from '../src/lib/codemirror'
import { uploadAttachment } from '../src/lib/attachments'

const mockedUpload = vi.mocked(uploadAttachment)

const views: EditorView[] = []
let parent: HTMLDivElement

function open(overrides: Partial<EditorSpec> = {}): EditorView {
  parent = document.createElement('div')
  document.body.append(parent)
  const view = createView({
    parent,
    doc: '',
    editable: true,
    placeholder: '',
    links: [],
    noteRef: 'NOTE-1',
    onSave: () => true,
    onChange: () => {},
    ...overrides,
  })
  views.push(view)
  return view
}

/**
 * A fake `DataTransfer`-shaped value. `.files` is what `lib/codemirror.ts`'s own handler reads;
 * `.getData` is a stub answering `''` — CM6's *own* built-in drop handler falls through to it when
 * ours declines an event (returns `false`, e.g. "no file"), and a value that lacked the method
 * entirely would throw from inside CM6's internals rather than exercising the fallback this test is
 * actually probing.
 */
function dropEvent(file: File | null): Event {
  const event = new Event('drop', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', {
    value: { files: { item: () => file }, getData: () => '' },
  })
  Object.defineProperty(event, 'clientX', { value: 0 })
  Object.defineProperty(event, 'clientY', { value: 0 })
  return event
}

/** `DataTransfer`-shaped's paste sibling — see {@link dropEvent}'s docstring for `.getData`. */
function pasteEvent(file: File | null): Event {
  const event = new Event('paste', { bubbles: true, cancelable: true })
  const items = file === null ? [] : [{ kind: 'file', getAsFile: () => file }]
  Object.defineProperty(event, 'clipboardData', { value: { items, getData: () => '' } })
  return event
}

function aFile(name = 'photo.png', bytes = 'pixels', type = 'image/png'): File {
  return new File([bytes], name, { type })
}

async function settle(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
}

afterEach(() => {
  for (const view of views.splice(0)) {
    view.destroy()
  }
  parent?.remove()
  mockedUpload.mockReset()
})

describe('drop-to-upload', () => {
  it('inserts a placeholder immediately, then resolves it to the uploaded markdown', async () => {
    let settleUpload: (value: { markdown: string }) => void = () => {}
    mockedUpload.mockReturnValue(
      new Promise((resolve) => {
        settleUpload = resolve
      }) as never,
    )

    const view = open()
    const dispatched = view.contentDOM.dispatchEvent(dropEvent(aFile('photo.png')))

    expect(dispatched).toBe(false) // `preventDefault()` was called, so dispatch reports handled
    expect(view.state.doc.toString()).toContain('Uploading photo.png…')
    expect(mockedUpload).toHaveBeenCalledWith('NOTE-1', expect.objectContaining({ name: 'photo.png' }))

    settleUpload({ markdown: '![photo.png](/api/v1/notes/NOTE-1/attachments/1)' })
    await settle()

    expect(view.state.doc.toString()).toBe('![photo.png](/api/v1/notes/NOTE-1/attachments/1)')
    expect(view.state.doc.toString()).not.toContain('Uploading')
  })

  it('inserts the file at the drop position, not always at the start', async () => {
    mockedUpload.mockResolvedValue({
      id: 1,
      content_type: 'image/png',
      size_bytes: 1,
      created_at: 'x',
      markdown: '![x](/api/v1/notes/NOTE-1/attachments/1)',
    })
    const view = open({ doc: 'before after' })
    view.posAtCoords = () => 6 // "before| after"

    view.contentDOM.dispatchEvent(dropEvent(aFile()))
    await settle()

    expect(view.state.doc.toString()).toBe('before![x](/api/v1/notes/NOTE-1/attachments/1) after')
  })

  it('removes the placeholder and reports the failure without inserting anything on a refusal', async () => {
    mockedUpload.mockRejectedValue(new Error('attachments are capped at 5 bytes'))
    const errors: string[] = []
    const view = open({ onAttachmentError: (message) => errors.push(message) })

    view.contentDOM.dispatchEvent(dropEvent(aFile()))
    expect(view.state.doc.toString()).toContain('Uploading')

    await settle()

    expect(view.state.doc.toString()).toBe('')
    expect(errors).toEqual(['attachments are capped at 5 bytes'])
  })

  it('does nothing and lets the browser handle it when there is no note open', () => {
    const view = open({ noteRef: null })

    const dispatched = view.contentDOM.dispatchEvent(dropEvent(aFile()))

    expect(dispatched).toBe(true) // not handled — no preventDefault was called
    expect(view.state.doc.toString()).toBe('')
    expect(mockedUpload).not.toHaveBeenCalled()
  })

  it('does nothing for an ordinary drop that carries no file', () => {
    const view = open()

    const dispatched = view.contentDOM.dispatchEvent(dropEvent(null))

    expect(dispatched).toBe(true)
    expect(view.state.doc.toString()).toBe('')
    expect(mockedUpload).not.toHaveBeenCalled()
  })
})

describe('paste-to-upload', () => {
  it('inserts a placeholder at the cursor and resolves it on success', async () => {
    mockedUpload.mockResolvedValue({
      id: 2,
      content_type: 'image/png',
      size_bytes: 1,
      created_at: 'x',
      markdown: '![clip.png](/api/v1/notes/NOTE-1/attachments/2)',
    })
    const view = open()

    view.contentDOM.dispatchEvent(pasteEvent(aFile('clip.png')))
    await settle()

    expect(view.state.doc.toString()).toBe('![clip.png](/api/v1/notes/NOTE-1/attachments/2)')
  })

  it('does nothing for an ordinary text paste', () => {
    const view = open()

    // Not asserted on `dispatched` here, unlike the drop case above: CM6's *own* built-in paste
    // handler runs after ours declines and intercepts a non-`null` `clipboardData` regardless of
    // whether it carried a file, so the event ends up handled either way. What is actually under
    // test is that *our* handler declined — never called `uploadAttachment` — and left CM6's
    // ordinary paste behaviour to run.
    view.contentDOM.dispatchEvent(pasteEvent(null))

    expect(mockedUpload).not.toHaveBeenCalled()
  })
})

describe('a placeholder edited away before the upload settles', () => {
  it('is not resurrected — the resolved markdown is silently dropped', async () => {
    let settleUpload: (value: { markdown: string }) => void = () => {}
    mockedUpload.mockReturnValue(
      new Promise((resolve) => {
        settleUpload = resolve
      }) as never,
    )
    const view = open()

    view.contentDOM.dispatchEvent(dropEvent(aFile()))
    expect(view.state.doc.toString()).toContain('Uploading')

    // The user selects everything and types over it before the upload settles.
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: 'something else' } })

    settleUpload({ markdown: '![x](/api/v1/notes/NOTE-1/attachments/1)' })
    await settle()

    expect(view.state.doc.toString()).toBe('something else')
  })
})
