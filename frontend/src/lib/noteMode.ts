/**
 * The Read | Edit | Split switch's decisions (KAN-1819) — pure, so each one is unit-tested without a
 * browser. `App.svelte` owns the state; `components/ModeSwitch.svelte` is the control. Nothing here
 * imports a component, and nothing here touches the editor: the mode changes the layout *around*
 * `EditorPane`, never its mount.
 *
 * - **read**: the rendered note alone.
 * - **edit**: the editor alone.
 * - **split**: editor and preview side by side. Only at `expanded` — two columns below 840px are two
 *   cramped columns — so the segment is *hidden* there, not disabled (the convention the sidebar's
 *   tree toggle already uses while a search is on).
 */

import type { WindowClass } from './windowClass'

export type NoteMode = 'read' | 'edit' | 'split'

/** In switch order. */
export const MODES: readonly NoteMode[] = ['read', 'edit', 'split']

export function modeAvailable(mode: NoteMode, windowClass: WindowClass): boolean {
  return mode !== 'split' || windowClass === 'expanded'
}

export function availableModes(windowClass: WindowClass): NoteMode[] {
  return MODES.filter((mode) => modeAvailable(mode, windowClass))
}

/**
 * What a note opens in with nothing remembered. Expanded is always Edit (the maintainer's call);
 * compact and medium open a saved note to read it, and a note the person just made through New note
 * in the editor, so they can start typing.
 */
export function defaultMode(windowClass: WindowClass, justCreated: boolean): NoteMode {
  if (windowClass === 'expanded') {
    return 'edit'
  }
  return justCreated ? 'edit' : 'read'
}

function asMode(value: unknown): NoteMode | null {
  return MODES.find((mode) => mode === value) ?? null
}

/**
 * The mode to show: the remembered one when it is a real mode this class offers, else the default.
 * A stored `split` at a class without it (a stale value, or a hand-edited one) lands on Edit rather
 * than the class default — the person was editing, so keep them there.
 *
 * A just-created note below expanded always opens in Edit: remembering Read must not make New note
 * land on a screen with nothing to type into.
 */
export function resolveMode(input: {
  windowClass: WindowClass
  stored: unknown
  justCreated: boolean
}): NoteMode {
  const { windowClass, stored, justCreated } = input
  if (justCreated && windowClass !== 'expanded') {
    return 'edit'
  }
  const remembered = asMode(stored)
  if (remembered === null) {
    return defaultMode(windowClass, justCreated)
  }
  return modeAvailable(remembered, windowClass) ? remembered : 'edit'
}

/** One key per class — compact and medium are different screens, so a different choice each. */
export function modeStorageKey(windowClass: WindowClass): string {
  return `kaya.noteMode.${windowClass}`
}

function defaultStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    // Merely *reading* `localStorage` throws in a sandboxed frame or with site data blocked.
    return null
  }
}

/** The remembered mode for a class, or `null` — never throws, whatever the storage does. */
export function readStoredMode(
  windowClass: WindowClass,
  storage: Storage | null = defaultStorage(),
): NoteMode | null {
  try {
    return asMode(storage?.getItem(modeStorageKey(windowClass)))
  } catch {
    return null
  }
}

/** Remember a choice for a class. A failure is swallowed: the choice still applies this session. */
export function writeStoredMode(
  windowClass: WindowClass,
  mode: NoteMode,
  storage: Storage | null = defaultStorage(),
): void {
  try {
    storage?.setItem(modeStorageKey(windowClass), mode)
  } catch {
    // Not remembered; the mode in memory is unaffected.
  }
}
