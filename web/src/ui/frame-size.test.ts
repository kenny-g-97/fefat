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

  it("keeps a height that fills until its edge has moved more than 8 px", () => {
    // A corner pulled sideways wobbles a little up or down: it pins no height, where a chart a
    // pixel taller than its page would lengthen the page and stop following the window.
    expect(
      draggedSize(FILLS, "corner", FILLING, { dx: -200, dy: 3 }, LIMITS)
    ).toEqual({ width: 760, height: null })
    expect(
      draggedSize(FILLS, "corner", FILLING, { dx: -200, dy: -8 }, LIMITS)
    ).toEqual({ width: 760, height: null })
    expect(
      draggedSize(FILLS, "bottom", FILLING, { dx: 0, dy: 9 }, LIMITS)
    ).toEqual({ width: null, height: 464 })
    // A height the trader set moves with the smallest pull.
    const set = { width: null, height: 400 }
    expect(
      draggedSize(
        set,
        "bottom",
        { width: 960, height: 400 },
        { dx: 0, dy: 3 },
        LIMITS
      )
    ).toEqual({ width: null, height: 403 })
  })
})

describe("a move that leaves an edge where it is drawn", () => {
  // Beside the open style drawer the chart's column is its least width, 576 px.
  const narrow = { ...LIMITS, mostWidth: 576 }
  const atLeast = { width: 576, height: 455 }
  const pinned = { width: 576, height: null }

  it("changes nothing, so that a frame that fills keeps filling and a set size stays set", () => {
    expect(
      draggedSize(FILLS, "right", atLeast, { dx: -100, dy: 0 }, narrow)
    ).toEqual(FILLS)
    expect(keyedSize(FILLS, "right", "ArrowLeft", atLeast, narrow)).toEqual(
      FILLS
    )
    expect(keyedSize(FILLS, "right", "Home", atLeast, narrow)).toEqual(FILLS)
    expect(
      draggedSize(pinned, "right", atLeast, { dx: -100, dy: 0 }, narrow)
    ).toEqual(pinned)
    expect(keyedSize(pinned, "right", "ArrowLeft", atLeast, narrow)).toEqual(
      pinned
    )
    // A width set wider than this column, drawn at the column's, stays set when its edge is
    // pushed at the column: a corner pulled down by a hand that wanders a pixel right.
    const wide = { width: 760, height: null }
    expect(
      draggedSize(wide, "corner", atLeast, { dx: 1, dy: 40 }, narrow)
    ).toEqual({ width: 760, height: 495 })
    expect(keyedSize(wide, "right", "ArrowRight", atLeast, narrow)).toEqual(
      wide
    )
    // A chart that fills at its least height keeps filling when pulled shorter.
    const short = { width: 960, height: 240 }
    expect(
      draggedSize(FILLS, "bottom", short, { dx: 0, dy: -50 }, LIMITS)
    ).toEqual(FILLS)
    expect(keyedSize(FILLS, "bottom", "Home", short, LIMITS)).toEqual(FILLS)
  })

  it("keeps a width within 8 px of its column the column's, at the least width too", () => {
    const column = { ...LIMITS, mostWidth: 580 }
    const drawn = { width: 580, height: 455 }

    expect(keyedSize(FILLS, "right", "ArrowLeft", drawn, column)).toEqual(FILLS)
    expect(
      draggedSize(FILLS, "right", drawn, { dx: -100, dy: 0 }, column)
    ).toEqual(FILLS)
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
