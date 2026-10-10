/**
 * KAY-165: the width of the two side panels, as pure functions (no DOM, no storage, so they are
 * unit-tested in node). `App.svelte` owns the state; `components/Resizer.svelte` owns the pointer.
 *
 * - The **left** panel is the note tree. It resizes at medium and expanded and collapses to zero.
 * - The **right** panel is the links/history pane. It resizes only where it sits *beside* the note
 *   (`supportingSurface(...).placement === 'beside'`, expanded); at medium it is below the note, so
 *   it has no width to change, and on compact it is a bottom sheet.
 *
 * A stored width is a preference. What renders is {@link effectiveLeft}/{@link effectiveRight}: the
 * preference clamped to what the window can spare, so a narrower window never rewrites the choice.
 */

import type { WindowClass } from "./windowClass";

export interface WidthSpec {
  min: number;
  max: number;
  default: number;
}

export const LEFT_WIDTH: WidthSpec = { min: 200, max: 460, default: 272 };
export const RIGHT_WIDTH: WidthSpec = { min: 240, max: 480, default: 300 };

/** Arrow-key step and the larger Shift+Arrow step, in CSS pixels. */
export const KEY_STEP = 16;
export const KEY_STEP_LARGE = 64;

/** The narrowest the note may get because of a panel (the document must stay usable). */
export const MIN_MAIN_WIDTH = 320;

/** The nav column's width per class, in px (`3.75rem` and `7rem` in `App.svelte`'s grid). */
export function navWidth(windowClass: WindowClass): number {
  return windowClass === "expanded" ? 112 : windowClass === "medium" ? 60 : 0;
}

export function clampWidth(value: number, spec: WidthSpec): number {
  if (!Number.isFinite(value)) {
    return spec.default;
  }
  return Math.min(spec.max, Math.max(spec.min, Math.round(value)));
}

/** The widest the left panel may be right now: the spec's max, less what the note and a beside-pane need. */
export function leftMax(
  viewport: number,
  windowClass: WindowClass,
  rightWidth: number,
): number {
  const room = viewport - navWidth(windowClass) - MIN_MAIN_WIDTH - rightWidth;
  return Math.max(LEFT_WIDTH.min, Math.min(LEFT_WIDTH.max, room));
}

export function rightMax(
  viewport: number,
  windowClass: WindowClass,
  leftWidth: number,
): number {
  const room = viewport - navWidth(windowClass) - MIN_MAIN_WIDTH - leftWidth;
  return Math.max(RIGHT_WIDTH.min, Math.min(RIGHT_WIDTH.max, room));
}

/** The left panel's rendered width: the preference, within what the window leaves for the note. */
export function effectiveLeft(
  stored: number,
  viewport: number,
  windowClass: WindowClass,
  rightWidth: number,
): number {
  return Math.min(
    leftMax(viewport, windowClass, rightWidth),
    clampWidth(stored, LEFT_WIDTH),
  );
}

/** The right panel's rendered width, within what the window leaves beside the note. */
export function effectiveRight(
  stored: number,
  viewport: number,
  windowClass: WindowClass,
  leftWidth: number,
): number {
  return Math.min(
    rightMax(viewport, windowClass, leftWidth),
    clampWidth(stored, RIGHT_WIDTH),
  );
}

export type PanelSide = "left" | "right";

/**
 * The width after a key on a separator, or `null` for a key it does not handle. Arrows move the
 * *edge*: Right moves it right, which widens the left panel and narrows the right one (whose edge
 * is its left side). Shift is the larger step; Home/End go to the limits.
 */
export function keyboardWidth(
  key: string,
  shift: boolean,
  current: number,
  side: PanelSide,
  min: number,
  max: number,
): number | null {
  const step = shift ? KEY_STEP_LARGE : KEY_STEP;
  const grow = side === "left" ? "ArrowRight" : "ArrowLeft";
  const shrink = side === "left" ? "ArrowLeft" : "ArrowRight";
  let next: number;
  if (key === grow) {
    next = current + step;
  } else if (key === shrink) {
    next = current - step;
  } else if (key === "Home") {
    next = min;
  } else if (key === "End") {
    next = max;
  } else {
    return null;
  }
  return Math.min(max, Math.max(min, next));
}

/** The width a drag arrives at: the start width moved by the pointer, clamped. */
export function dragWidth(
  startWidth: number,
  startX: number,
  x: number,
  side: PanelSide,
  min: number,
  max: number,
): number {
  const delta = side === "left" ? x - startX : startX - x;
  return Math.min(max, Math.max(min, Math.round(startWidth + delta)));
}

/** What is remembered for one window class. `null` widths mean "never chosen: use the default". */
export interface PanelPrefs {
  left: number | null;
  right: number | null;
  leftOpen: boolean;
}

export const DEFAULT_PANELS: PanelPrefs = {
  left: null,
  right: null,
  leftOpen: true,
};

/** One key per class, like the pane and mode choices: medium and expanded are different rooms. */
export function panelsStorageKey(windowClass: WindowClass): string {
  return `kaya.panels.${windowClass}`;
}

export function encodePanels(prefs: PanelPrefs): string {
  return JSON.stringify({
    left: prefs.left,
    right: prefs.right,
    leftOpen: prefs.leftOpen,
  });
}

function widthOrNull(value: unknown, spec: WidthSpec): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? clampWidth(value, spec)
    : null;
}

/** Total: anything unreadable (missing, corrupt, wrong types) is the default, never a throw. */
export function decodePanels(raw: string | null | undefined): PanelPrefs {
  if (typeof raw !== "string") {
    return { ...DEFAULT_PANELS };
  }
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) {
      return { ...DEFAULT_PANELS };
    }
    const record = value as Record<string, unknown>;
    return {
      left: widthOrNull(record.left, LEFT_WIDTH),
      right: widthOrNull(record.right, RIGHT_WIDTH),
      leftOpen: record.leftOpen !== false,
    };
  } catch {
    return { ...DEFAULT_PANELS };
  }
}
