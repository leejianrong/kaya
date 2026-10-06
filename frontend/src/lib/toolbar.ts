/**
 * KAN-1826: the mobile formatting toolbar's buttons and when it shows.
 *
 * Pure and CodeMirror-free, like `lib/shell.ts`. `EditorToolbar.svelte` renders it and talks to the
 * editor only through {@link EditorCommands}, an interface `lib/codemirror.ts` implements, so the
 * component never imports `@codemirror/*` (`tests/module-graph.ts`) and `EditorPane.svelte` still
 * owns nothing but its container.
 */

import type { FormatAction } from './formatting'
import type { NoteMode } from './noteMode'
import type { WindowClass } from './windowClass'

export type ToolbarAction = FormatAction | 'undo'

export interface ToolbarButton {
  action: ToolbarAction
  /** The accessible name; the visible face is an icon. */
  label: string
}

/** Left to right. Undo sits last, apart from the formatting actions. */
export const TOOLBAR_BUTTONS: readonly ToolbarButton[] = [
  { action: 'bold', label: 'Bold' },
  { action: 'italic', label: 'Italic' },
  { action: 'list', label: 'Bulleted list' },
  { action: 'checkbox', label: 'Checkbox list' },
  { action: 'code', label: 'Code' },
  { action: 'link', label: 'Link' },
  { action: 'wikilink', label: 'Wikilink' },
  { action: 'undo', label: 'Undo' },
]

/** What the toolbar may ask of the live editor. `null` while there is no editor. */
export interface EditorCommands {
  run(action: ToolbarAction): void
  /** Scroll the caret into the visible part of the editor, after the keyboard moved. */
  revealCaret(): void
}

/**
 * The toolbar belongs to editing with a soft keyboard: Edit mode on a compact or medium window,
 * while the editor has focus. Split exists only at `expanded`, where there is a hardware keyboard
 * to assume, so there is no toolbar to compare it with.
 */
export function toolbarShown(input: {
  windowClass: WindowClass
  mode: NoteMode
  focused: boolean
  inNote: boolean
}): boolean {
  return input.inNote && input.focused && input.mode === 'edit' && input.windowClass !== 'expanded'
}
