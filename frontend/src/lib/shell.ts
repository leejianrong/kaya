/**
 * What the shell renders for a window class and a route (KAN-1818) — pure, so it is unit-tested
 * without a browser. `App.svelte` is the only consumer.
 *
 * - **compact**: the list and the note are separate screens (`home` is the list; every other
 *   route is `main` alone). Backlinks and history are a modal bottom sheet.
 * - **medium**: list beside the note; backlinks and history are a pane below the note.
 * - **expanded**: list, note and a pane beside the note.
 *
 * KAN-1827: the supporting surface (backlinks + history) is closed by default at every size. The
 * document keeps the width; the person opens the surface from the note's top bar. {@link
 * supportingSurface} is the one place that decides which kind renders.
 */

import {
  decodePanels,
  encodePanels,
  panelsStorageKey,
  type PanelPrefs,
} from "./panels";
import type { Route } from "./router";
import type { WindowClass } from "./windowClass";

export interface Regions {
  /** The primary navigation (a bottom bar on compact, a rail otherwise). */
  nav: boolean;
  /** The note list (`Sidebar`). */
  list: boolean;
  /** `main`: the document, or graph/settings/etc. */
  main: boolean;
  /** The backlinks/history surface (KAN-1827): a sheet, a pane, or nothing. */
  supporting: Supporting;
}

export type SupportingKind = "sheet" | "pane" | "none";

export interface Supporting {
  kind: SupportingKind;
  /** Where a pane sits. `null` for a sheet (it floats above everything) and for `none`. */
  placement: "beside" | "below" | null;
  /** Whether it starts open. Always `false`: the document keeps the width until asked. */
  defaultOpen: boolean;
}

const NO_SUPPORT: Supporting = {
  kind: "none",
  placement: null,
  defaultOpen: false,
};

/**
 * Which supporting surface a window class gets for a route. Only a note has anything to say about
 * itself, so every other route (and no credential) is `none`.
 *
 * Compact is a sheet: a phone has no room for a pane. Medium (a list and a note already share the
 * width) gets a pane below the note, which is where the rail already sat. Expanded gets a pane
 * beside it.
 */
export function supportingSurface(
  windowClass: WindowClass,
  route: Route,
  authed: boolean,
): Supporting {
  if (!authed || route.name !== "note") {
    return NO_SUPPORT;
  }
  if (windowClass === "compact") {
    return { kind: "sheet", placement: null, defaultOpen: false };
  }
  return {
    kind: "pane",
    placement: windowClass === "medium" ? "below" : "beside",
    defaultOpen: false,
  };
}

/** One key per class, like `noteMode.ts`: medium and expanded are different amounts of room. */
export function paneStorageKey(windowClass: WindowClass): string {
  return `kaya.supportPane.${windowClass}`;
}

function defaultStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** The remembered open/closed state for a class, or `null`. Never throws. */
export function readStoredPaneOpen(
  windowClass: WindowClass,
  storage: Storage | null = defaultStorage(),
): boolean | null {
  try {
    const value = storage?.getItem(paneStorageKey(windowClass));
    return value === "open" ? true : value === "closed" ? false : null;
  } catch {
    return null;
  }
}

/** Remember it. A failure is swallowed: the choice still applies this session. */
export function writeStoredPaneOpen(
  windowClass: WindowClass,
  open: boolean,
  storage: Storage | null = defaultStorage(),
): void {
  try {
    storage?.setItem(paneStorageKey(windowClass), open ? "open" : "closed");
  } catch {
    // Not remembered.
  }
}

/** The remembered panel widths and left-panel state for a class (KAY-165). Never throws. */
export function readStoredPanels(
  windowClass: WindowClass,
  storage: Storage | null = defaultStorage(),
): PanelPrefs {
  try {
    return decodePanels(storage?.getItem(panelsStorageKey(windowClass)));
  } catch {
    return decodePanels(null);
  }
}

/** Remember them. A failure is swallowed: the choice still applies this session. */
export function writeStoredPanels(
  windowClass: WindowClass,
  prefs: PanelPrefs,
  storage: Storage | null = defaultStorage(),
): void {
  try {
    storage?.setItem(panelsStorageKey(windowClass), encodePanels(prefs));
  } catch {
    // Not remembered.
  }
}

/**
 * Whether the list's width can be changed or the list collapsed: it sits beside the note at medium
 * and expanded. On compact it is a full screen of its own.
 */
export function panelsResizable(windowClass: WindowClass): boolean {
  return windowClass !== "compact";
}

/** Whether the pane has a width of its own to change: only where it sits beside the note. */
export function supportingResizable(supporting: Supporting): boolean {
  return supporting.kind === "pane" && supporting.placement === "beside";
}

/** Open or closed on arrival: the remembered answer for a pane, otherwise the default. */
export function resolvePaneOpen(
  supporting: Supporting,
  stored: boolean | null,
): boolean {
  if (supporting.kind !== "pane") {
    return false;
  }
  return stored ?? supporting.defaultOpen;
}

export function shellRegions(
  windowClass: WindowClass,
  route: Route,
  authed: boolean,
): Regions {
  if (!authed) {
    // `tokens`/`device` are reachable with no credential and render in `main` alone (KAN-1739).
    return { nav: false, list: false, main: true, supporting: NO_SUPPORT };
  }
  const compact = windowClass === "compact";
  const listRoute = route.name !== "tokens" && route.name !== "device";
  const list = listRoute && (!compact || route.name === "home");
  const main = !(compact && route.name === "home");
  return {
    nav: true,
    list,
    main,
    supporting: supportingSurface(windowClass, route, authed),
  };
}

export interface NavDestination {
  label: string;
  href: string;
  icon: "notes" | "graph" | "settings";
  isActive: (route: Route) => boolean;
}

/** The three primary destinations. Tokens and the pandan link live under Settings. */
export const NAV_DESTINATIONS: readonly NavDestination[] = [
  {
    label: "Notes",
    href: "/",
    icon: "notes",
    isActive: (r) => r.name === "home" || r.name === "note",
  },
  {
    label: "Graph",
    href: "/graph",
    icon: "graph",
    isActive: (r) => r.name === "graph",
  },
  {
    label: "Settings",
    href: "/settings",
    icon: "settings",
    isActive: (r) =>
      r.name === "settings" || r.name === "tokens" || r.name === "pandan",
  },
];

export function navActive(destination: NavDestination, route: Route): boolean {
  return destination.isActive(route);
}
