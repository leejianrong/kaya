/**
 * KAY-165: the note list and the links pane resize by drag and keyboard, collapse, and remember
 * both per window class. A real browser, because layout and pointer capture are what is under test.
 * The jsdom half (ARIA, storage, Ctrl+B wiring) is `tests/panels-shell.test.ts`.
 */
import type { Page } from "@playwright/test";

import {
  apiCreateNote,
  apiDeleteNote,
  expect,
  prefixedTitle,
  test,
} from "./fixtures";

const width = async (page: Page, selector: string): Promise<number> =>
  Math.round((await page.locator(selector).boundingBox())!.width);

test("expanded: drag, double-click reset, keyboard, collapse and reload persistence", async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle("panels"),
    body: "Panels.\n",
  });
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/notes/${note.ref}`);
    const separator = page.getByTestId("resizer-left");
    await expect(separator).toBeVisible();
    expect(await width(page, "#list-panel")).toBe(272);
    await expect(separator).toHaveAttribute("role", "separator");
    await expect(separator).toHaveAttribute("aria-valuenow", "272");

    // A real drag, with the pointer captured: the width follows and text selection is off.
    const box = (await separator.boundingBox())!;
    const x = box.x + box.width / 2;
    await page.mouse.move(x, 400);
    await page.mouse.down();
    await page.mouse.move(x + 80, 400, { steps: 5 });
    expect(await page.evaluate(() => document.body.style.userSelect)).toBe(
      "none",
    );
    await page.mouse.up();
    expect(await width(page, "#list-panel")).toBe(352);
    await expect(separator).toHaveAttribute("aria-valuenow", "352");
    expect(await page.evaluate(() => document.body.style.userSelect)).toBe("");

    // Limits: 200 to 460.
    const edge = (await separator.boundingBox())!;
    await page.mouse.move(edge.x + 4, 400);
    await page.mouse.down();
    await page.mouse.move(edge.x + 900, 400, { steps: 4 });
    await page.mouse.up();
    expect(await width(page, "#list-panel")).toBe(460);

    // Double-click resets; the keyboard steps by 16, Shift by 64.
    await separator.dblclick();
    expect(await width(page, "#list-panel")).toBe(272);
    await separator.focus();
    await page.keyboard.press("ArrowRight");
    expect(await width(page, "#list-panel")).toBe(288);
    await page.keyboard.press("Shift+ArrowRight");
    expect(await width(page, "#list-panel")).toBe(352);

    // The links pane: same, from its left edge, against the pointer.
    await page.getByTestId("toggle-details").click();
    const rail = page.getByTestId("resizer-right");
    await expect(rail).toHaveAttribute("aria-valuenow", "300");
    await rail.focus();
    await page.keyboard.press("Shift+ArrowLeft");
    expect(await width(page, ".right-rail")).toBe(364);

    // Both widths survive a reload.
    await page.reload();
    await expect(page.getByTestId("resizer-left")).toHaveAttribute(
      "aria-valuenow",
      "352",
    );
    expect(await width(page, ".right-rail")).toBe(364);

    // Collapse: zero width, nothing inside is tabbable, and it is remembered.
    await page.getByTestId("toggle-list").click();
    await expect(page.locator("#list-panel")).toHaveJSProperty("inert", true);
    await expect.poll(() => width(page, "#list-panel")).toBe(0);
    await expect(page.getByTestId("toggle-list")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await page.locator("body").click({ position: { x: 700, y: 5 } });
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      expect(
        await page.evaluate(
          () => !!document.activeElement?.closest("#list-panel"),
        ),
      ).toBe(false);
    }
    await page.reload();
    await expect(page.getByTestId("toggle-list")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(await width(page, "#list-panel")).toBe(0);

    // Ctrl+B brings it back at the width it had.
    await page.keyboard.press("Control+b");
    await expect.poll(() => width(page, "#list-panel")).toBe(352);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
  } finally {
    await apiDeleteNote(request, note.ref);
  }
});

test("medium: the list resizes within what the note can spare; the pane stays below with no handle", async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle("panels-m"),
    body: "Medium.\n",
  });
  try {
    await page.setViewportSize({ width: 720, height: 900 });
    await page.goto(`/notes/${note.ref}`);
    await expect(page.getByTestId("resizer-left")).toBeVisible();
    await page.getByTestId("toggle-details").click();
    await expect(page.locator(".right-rail")).toBeVisible();
    await expect(page.getByTestId("resizer-right")).toHaveCount(0);

    const edge = (await page.getByTestId("resizer-left").boundingBox())!;
    await page.mouse.move(edge.x + 4, 300);
    await page.mouse.down();
    await page.mouse.move(edge.x + 500, 300, { steps: 4 });
    await page.mouse.up();
    expect(await width(page, "main")).toBeGreaterThanOrEqual(320);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
  } finally {
    await apiDeleteNote(request, note.ref);
  }
});

test("compact: a full-screen list, no handles, no panel button, and Links stays a sheet", async ({
  authedPage: page,
  request,
}) => {
  const note = await apiCreateNote(request, {
    title: prefixedTitle("panels-c"),
    body: "Compact.\n",
    path: "panels-folder/compact.md",
  });
  try {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto("/");
    await expect(page.locator(".sidebar")).toBeVisible();
    expect(await width(page, ".sidebar")).toBe(390);
    await expect(page.locator('[role="separator"]')).toHaveCount(0);
    await expect(page.getByTestId("toggle-list")).toHaveCount(0);

    // A folder row sits at the left edge, not centred (`.row` centres its content in compact).
    const folder = page.locator(".row.folder").first();
    await expect(folder).toBeVisible();
    const rowBox = (await folder.boundingBox())!;
    const labelBox = (await folder.locator("*").first().boundingBox())!;
    expect(labelBox.x - rowBox.x).toBeLessThan(40);

    await page.goto(`/notes/${note.ref}`);
    await page.getByTestId("toggle-details").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.locator('[role="separator"]')).toHaveCount(0);
  } finally {
    await apiDeleteNote(request, note.ref);
  }
});
