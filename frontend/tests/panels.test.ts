/** KAY-165: the pure width arithmetic and the per-class persistence format. */
import { describe, expect, it } from "vitest";

import {
  clampWidth,
  decodePanels,
  DEFAULT_PANELS,
  dragWidth,
  effectiveLeft,
  effectiveRight,
  encodePanels,
  keyboardWidth,
  KEY_STEP,
  KEY_STEP_LARGE,
  LEFT_WIDTH,
  leftMax,
  MIN_MAIN_WIDTH,
  panelsStorageKey,
  RIGHT_WIDTH,
  rightMax,
} from "../src/lib/panels";

describe("the width limits", () => {
  it("are the card numbers", () => {
    expect(LEFT_WIDTH).toEqual({ min: 200, max: 460, default: 272 });
    expect(RIGHT_WIDTH).toEqual({ min: 240, max: 480, default: 300 });
  });

  it("clamp, round, and fall back to the default for a non-number", () => {
    expect(clampWidth(100, LEFT_WIDTH)).toBe(200);
    expect(clampWidth(9999, LEFT_WIDTH)).toBe(460);
    expect(clampWidth(300.6, LEFT_WIDTH)).toBe(301);
    expect(clampWidth(Number.NaN, RIGHT_WIDTH)).toBe(300);
  });
});

describe("what the window can spare", () => {
  it("keeps the note usable: the left panel gives way first at medium", () => {
    // 600px - 60px nav - 320px note = 220px for the list, however wide it was asked to be.
    expect(leftMax(600, "medium", 0)).toBe(220);
    expect(effectiveLeft(400, 600, "medium", 0)).toBe(220);
    expect(effectiveLeft(272, 800, "medium", 0)).toBe(272);
  });

  it("never goes below the minimum, even when the note would shrink", () => {
    expect(leftMax(840, "expanded", 480)).toBe(LEFT_WIDTH.min);
    expect(rightMax(840, "expanded", 460)).toBe(RIGHT_WIDTH.min);
  });

  it("leaves the stored preference alone on a wide window", () => {
    expect(effectiveLeft(400, 1440, "expanded", 300)).toBe(400);
    expect(effectiveRight(400, 1440, "expanded", 400)).toBe(400);
    expect(1440 - 112 - 400 - 400).toBeGreaterThanOrEqual(MIN_MAIN_WIDTH);
  });
});

describe("keyboardWidth", () => {
  it("Right widens the left panel and narrows the right one: arrows move the edge", () => {
    expect(keyboardWidth("ArrowRight", false, 272, "left", 200, 460)).toBe(
      272 + KEY_STEP,
    );
    expect(keyboardWidth("ArrowLeft", false, 272, "left", 200, 460)).toBe(
      272 - KEY_STEP,
    );
    expect(keyboardWidth("ArrowLeft", false, 300, "right", 240, 480)).toBe(
      300 + KEY_STEP,
    );
    expect(keyboardWidth("ArrowRight", false, 300, "right", 240, 480)).toBe(
      300 - KEY_STEP,
    );
  });

  it("Shift takes the larger step, Home/End the limits, and the result is clamped", () => {
    expect(keyboardWidth("ArrowRight", true, 272, "left", 200, 460)).toBe(
      272 + KEY_STEP_LARGE,
    );
    expect(keyboardWidth("ArrowLeft", true, 210, "left", 200, 460)).toBe(200);
    expect(keyboardWidth("Home", false, 300, "left", 200, 460)).toBe(200);
    expect(keyboardWidth("End", false, 300, "right", 240, 480)).toBe(480);
  });

  it("declines every other key", () => {
    expect(keyboardWidth("a", false, 272, "left", 200, 460)).toBeNull();
    expect(keyboardWidth("ArrowUp", false, 272, "left", 200, 460)).toBeNull();
  });
});

describe("dragWidth", () => {
  it("follows the pointer from the left panel and against it from the right one", () => {
    expect(dragWidth(272, 100, 150, "left", 200, 460)).toBe(322);
    expect(dragWidth(300, 900, 850, "right", 240, 480)).toBe(350);
  });

  it("clamps at both ends", () => {
    expect(dragWidth(272, 100, -500, "left", 200, 460)).toBe(200);
    expect(dragWidth(272, 100, 5000, "left", 200, 460)).toBe(460);
  });
});

describe("persistence", () => {
  it("is keyed per window class", () => {
    expect(panelsStorageKey("medium")).not.toBe(panelsStorageKey("expanded"));
  });

  it("round-trips", () => {
    const prefs = { left: 310, right: 400, leftOpen: false };
    expect(decodePanels(encodePanels(prefs))).toEqual(prefs);
    expect(decodePanels(encodePanels(DEFAULT_PANELS))).toEqual(DEFAULT_PANELS);
  });

  it("is total: missing, corrupt and wrong-typed storage is the default", () => {
    for (const raw of [
      null,
      undefined,
      "",
      "nope",
      "[]",
      "null",
      "42",
      '{"left":"wide","leftOpen":1}',
    ]) {
      expect(decodePanels(raw)).toEqual(DEFAULT_PANELS);
    }
  });

  it("clamps a stored width that is out of range", () => {
    expect(decodePanels('{"left":5,"right":99999}')).toEqual({
      left: 200,
      right: 480,
      leftOpen: true,
    });
  });
});
