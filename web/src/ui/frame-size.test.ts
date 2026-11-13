import { describe, expect, it } from "vitest"
import { draggedSize, FILLS, keyedSize } from "./frame-size"

// From the builder's third check of step 5.4: the chart's frame is dragged by its edges. The
// limits here are the chart's: never under 576 by 240 px, never over 1600 px tall, and no wider
// than its column, 960 px at 1280 by 800.
const LIMITS = {
  leastWidth: 576,
  leastHeight: 240,
  mostWidth: 960,
  mostHeight: 1600,
}
const FILLING = { width: 960, height: 455.5 }

describe("draggedSize", () => {
  it("moves the edge it is given by the pointer's move, and leaves the other dimension", () => {
    expect(
      draggedSize(FILLS, "right", FILLING, { dx: -200, dy: 30 }, LIMITS)
    ).toEqual({ width: 760, height: null })
    expect(
      draggedSize(FILLS, "bottom", FILLING, { dx: 50, dy: -80 }, LIMITS)
    ).toEqual({ width: null, height: 375 })
    expect(
      draggedSize(FILLS, "corner", FILLING, { dx: -40.4, dy: 40.4 }, LIMITS)
    ).toEqual({ width: 920, height: 495 })
  })

  it("changes nothing while the pointer has not moved, so that a press pins no size", () => {
    expect(
      draggedSize(FILLS, "corner", FILLING, { dx: 0, dy: 0 }, LIMITS)
    ).toEqual(FILLS)
    expect(
      draggedSize(FILLS, "corner", FILLING, { dx: 0, dy: 10 }, LIMITS)
    ).toEqual({ width: null, height: 465 })
  })

  it("keeps the least and the most, and a width back at its column fills again", () => {
    const narrow = { width: 760, height: 455 }
    const set = { width: 760, height: 455 }

    expect(
      draggedSize(FILLS, "right", FILLING, { dx: -700, dy: 0 }, LIMITS).width
    ).toBe(576)
    expect(
      draggedSize(FILLS, "bottom", FILLING, { dx: 0, dy: -400 }, LIMITS).height
    ).toBe(240)
    expect(
      draggedSize(FILLS, "bottom", FILLING, { dx: 0, dy: 5000 }, LIMITS).height
    ).toBe(1600)
    // Within 8 px of the column the width is the column's, which a drawer may narrow later.
    expect(
      draggedSize(set, "right", narrow, { dx: 191, dy: 0 }, LIMITS).width
    ).toBe(951)
    expect(
      draggedSize(set, "right", narrow, { dx: 192, dy: 0 }, LIMITS).width
    ).toBeNull()
    expect(
      draggedSize(set, "corner", narrow, { dx: 320, dy: 0 }, LIMITS)
    ).toEqual({ width: null, height: 455 })
  })
})

describe("keyedSize", () => {
  it("moves the right edge by the left and right arrows, 16 px a press", () => {
    const narrower = keyedSize(FILLS, "right", "ArrowLeft", FILLING, LIMITS)

    expect(narrower).toEqual({ width: 944, height: null })
    expect(
      keyedSize(
        { width: 800, height: 300 },
        "right",
        "ArrowRight",
        { width: 800, height: 300 },
        LIMITS
      )
    ).toEqual({ width: 816, height: 300 })
    expect(keyedSize(FILLS, "right", "ArrowRight", FILLING, LIMITS)).toEqual(
      FILLS
    )
  })

  it("moves the bottom edge by the up and down arrows", () => {
    expect(keyedSize(FILLS, "bottom", "ArrowUp", FILLING, LIMITS)).toEqual({
      width: null,
      height: 439,
    })
    expect(keyedSize(FILLS, "bottom", "ArrowDown", FILLING, LIMITS)).toEqual({
      width: null,
      height: 471,
    })
  })

  it("goes to the least on Home and the most on End, and fills again on Enter", () => {
    const set = { width: 760, height: 400 }
    const drawn = { width: 760, height: 400 }

    expect(keyedSize(set, "right", "Home", drawn, LIMITS)).toEqual({
      width: 576,
      height: 400,
    })
    expect(keyedSize(set, "right", "End", drawn, LIMITS)).toEqual({
      width: null,
      height: 400,
    })
    expect(keyedSize(set, "bottom", "Home", drawn, LIMITS)).toEqual({
      width: 760,
      height: 240,
    })
    expect(keyedSize(set, "bottom", "End", drawn, LIMITS)).toEqual({
      width: 760,
      height: 1600,
    })
    expect(keyedSize(set, "right", "Enter", drawn, LIMITS)).toEqual({
      width: null,
      height: 400,
    })
    expect(keyedSize(set, "bottom", "Enter", drawn, LIMITS)).toEqual({
      width: 760,
      height: null,
    })
  })

  it("leaves a key that is not the edge's to the page", () => {
    expect(
      keyedSize(FILLS, "right", "ArrowUp", FILLING, LIMITS)
    ).toBeUndefined()
    expect(
      keyedSize(FILLS, "bottom", "ArrowLeft", FILLING, LIMITS)
    ).toBeUndefined()
    expect(keyedSize(FILLS, "right", "Tab", FILLING, LIMITS)).toBeUndefined()
  })
})
