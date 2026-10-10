// @vitest-environment jsdom
/**
 * KAY-165: the shell wiring for the side panels. jsdom has no layout, so this asserts what renders
 * and what is remembered; `e2e/panels.spec.ts` drives the real drag in a browser.
 */
import { flushSync, mount, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App.svelte";
import * as auth from "../src/lib/auth";
import { panelsStorageKey } from "../src/lib/panels";
import {
  readStoredPanels,
  supportingResizable,
  writeStoredPanels,
} from "../src/lib/shell";
import { FAKE_TOKEN } from "./token";

const NOTE = {
  ref: "NOTE-6",
  id: 6,
  title: "Weekly review",
  body: "hello",
  path: "journal/review.md",
  created_at: "2026-08-09T10:00:00+00:00",
  updated_at: "2026-08-09T10:00:00.123456+00:00",
  team_id: null,
};

/** jsdom does not reflect the `inert` property to an attribute; a browser does (e2e checks it). */
function inert(el: Element | null): boolean {
  return (
    el !== null &&
    (el.hasAttribute("inert") ||
      (el as HTMLElement & { inert?: boolean }).inert === true)
  );
}

let host: HTMLDivElement;
let instance: unknown;
const realFetch = globalThis.fetch;
const realPathname = window.location.pathname;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function open(
  width: number,
  path = "/notes/NOTE-6",
): Promise<HTMLElement> {
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = Number(/min-width: (\d+)px/.exec(query)![1]);
    return {
      matches: width >= min,
      addEventListener() {},
      removeEventListener() {},
    };
  });
  window.history.pushState({}, "", path);
  auth.setToken(FAKE_TOKEN);
  instance = mount(App, { target: host, props: {} });
  flushSync();
  await vi.waitFor(() => {
    flushSync();
    expect(host.querySelector('[data-testid="nav-column"]')).not.toBeNull();
  });
  return host.querySelector(".shell") as HTMLElement;
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/v1/notes") return json(200, { notes: [NOTE] });
    if (url === "/api/v1/notes/NOTE-6") return json(200, NOTE);
    if (url.startsWith("/api/v1/notes/NOTE-6/"))
      return json(200, { backlinks: [], versions: [], links: [] });
    return json(404, {
      error: { code: "not_found", message: `nothing fake at ${url}` },
    });
  }) as unknown as typeof fetch;
});

afterEach(() => {
  localStorage.clear();
  unmount(instance as never);
  host.remove();
  auth.clearToken();
  vi.unstubAllGlobals();
  globalThis.fetch = realFetch;
  window.history.pushState({}, "", realPathname);
});

describe("storage seam", () => {
  it("reads defaults, round-trips, and survives a throwing storage", () => {
    expect(readStoredPanels("expanded")).toEqual({
      left: null,
      right: null,
      leftOpen: true,
    });
    writeStoredPanels("expanded", { left: 300, right: null, leftOpen: false });
    expect(readStoredPanels("expanded").left).toBe(300);
    expect(readStoredPanels("medium").left).toBeNull();
    const broken = {
      getItem() {
        throw new Error("blocked");
      },
      setItem() {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(readStoredPanels("expanded", broken).leftOpen).toBe(true);
    expect(() =>
      writeStoredPanels(
        "expanded",
        { left: 1, right: 1, leftOpen: true },
        broken,
      ),
    ).not.toThrow();
  });

  it("gives only a beside pane a width of its own", () => {
    expect(
      supportingResizable({
        kind: "pane",
        placement: "beside",
        defaultOpen: false,
      }),
    ).toBe(true);
    expect(
      supportingResizable({
        kind: "pane",
        placement: "below",
        defaultOpen: false,
      }),
    ).toBe(false);
    expect(
      supportingResizable({
        kind: "sheet",
        placement: null,
        defaultOpen: false,
      }),
    ).toBe(false);
  });
});

describe("the left panel", () => {
  it("expanded: the separator carries its ARIA contract and the width var is the default", async () => {
    const shell = await open(1440);
    const separator = host.querySelector(
      '[data-testid="resizer-left"]',
    ) as HTMLElement;
    expect(separator.getAttribute("role")).toBe("separator");
    expect(separator.getAttribute("aria-orientation")).toBe("vertical");
    expect(separator.getAttribute("aria-valuenow")).toBe("272");
    expect(separator.getAttribute("aria-valuemin")).toBe("200");
    expect(separator.getAttribute("aria-valuemax")).toBe("460");
    expect(shell.style.getPropertyValue("--left-col")).toBe("272px");
  });

  it("arrow keys resize it, the width is remembered for this class only, double-click resets", async () => {
    const shell = await open(1440);
    const separator = host.querySelector(
      '[data-testid="resizer-left"]',
    ) as HTMLElement;
    separator.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "ArrowRight",
        shiftKey: true,
        bubbles: true,
      }),
    );
    flushSync();
    expect(shell.style.getPropertyValue("--left-col")).toBe("336px");
    expect(
      JSON.parse(localStorage.getItem(panelsStorageKey("expanded"))!).left,
    ).toBe(336);
    expect(localStorage.getItem(panelsStorageKey("medium"))).toBeNull();
    separator.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    flushSync();
    expect(shell.style.getPropertyValue("--left-col")).toBe("272px");
  });

  it("the top-bar button and Ctrl/Cmd+B collapse it to zero and make it inert", async () => {
    const shell = await open(1440);
    const button = host.querySelector(
      '[data-testid="toggle-list"]',
    ) as HTMLButtonElement;
    const panel = host.querySelector("#list-panel") as HTMLElement;
    expect(button.getAttribute("aria-expanded")).toBe("true");
    button.click();
    flushSync();
    expect(shell.style.getPropertyValue("--left-col")).toBe("0px");
    expect(inert(panel)).toBe(true);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(host.querySelector('[data-testid="resizer-left"]')).toBeNull();
    expect(
      JSON.parse(localStorage.getItem(panelsStorageKey("expanded"))!).leftOpen,
    ).toBe(false);

    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "b",
        ctrlKey: true,
        cancelable: true,
      }),
    );
    flushSync();
    expect(shell.style.getPropertyValue("--left-col")).toBe("272px");
    expect(inert(panel)).toBe(false);
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "b",
        metaKey: true,
        cancelable: true,
      }),
    );
    flushSync();
    expect(shell.style.getPropertyValue("--left-col")).toBe("0px");
  });

  it("medium: resizable and collapsible, with the pane below the note (no right separator)", async () => {
    await open(700);
    expect(host.querySelector('[data-testid="resizer-left"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="toggle-list"]')).not.toBeNull();
    (
      host.querySelector('[data-testid="toggle-details"]') as HTMLButtonElement
    ).click();
    flushSync();
    expect(host.querySelector(".right-rail")).not.toBeNull();
    expect(host.querySelector('[data-testid="resizer-right"]')).toBeNull();
  });

  it("compact: no handles, no panel button, and Ctrl+B does nothing", async () => {
    await open(390, "/");
    expect(host.querySelector(".sidebar")).not.toBeNull();
    expect(host.querySelector('[data-testid="resizer-left"]')).toBeNull();
    expect(host.querySelector('[data-testid="resizer-right"]')).toBeNull();
    expect(host.querySelector('[data-testid="toggle-list"]')).toBeNull();
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "b",
        ctrlKey: true,
        cancelable: true,
      }),
    );
    flushSync();
    expect(localStorage.getItem(panelsStorageKey("compact"))).toBeNull();
    expect(inert(host.querySelector("#list-panel"))).toBe(false);
  });
});

describe("the right panel", () => {
  it("expanded: a separator on its left edge, resized by the keyboard against the edge", async () => {
    const shell = await open(1440);
    (
      host.querySelector('[data-testid="toggle-details"]') as HTMLButtonElement
    ).click();
    flushSync();
    const separator = host.querySelector(
      '[data-testid="resizer-right"]',
    ) as HTMLElement;
    expect(separator.getAttribute("aria-valuenow")).toBe("300");
    expect(separator.getAttribute("aria-valuemin")).toBe("240");
    expect(shell.style.getPropertyValue("--right-col")).toBe("300px");
    separator.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }),
    );
    flushSync();
    expect(shell.style.getPropertyValue("--right-col")).toBe("316px");
    expect(
      JSON.parse(localStorage.getItem(panelsStorageKey("expanded"))!).right,
    ).toBe(316);
  });
});
