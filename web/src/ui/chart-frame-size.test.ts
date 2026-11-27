import { describe, expect, it } from "vitest"
import { storedFrameSize } from "./chart-frame-size"
import { FILLS } from "./frame-size"

describe("storedFrameSize", () => {
  it("reads the size the browser kept, a direction that fills as null", () => {
    expect(storedFrameSize('{"width":760,"height":400}', FILLS)).toEqual({
      width: 760,
      height: 400,
    })
    expect(storedFrameSize('{"width":null,"height":1600}', FILLS)).toEqual({
      width: null,
      height: 1600,
    })
    // A height past the chart's most is a size still: a window taller than 1600 px holds a
    // taller chart, and the frame draws none taller than its most (chart-size.spec.ts).
    expect(storedFrameSize('{"width":760,"height":5000}', FILLS)).toEqual({
      width: 760,
      height: 5000,
    })
    expect(storedFrameSize('{"width":null,"height":null}', FILLS)).toEqual(
      FILLS
    )
  })

  it("reads a chart that fills where nothing is kept, or what is kept is no size of the chart's", () => {
    // Local storage is the trader's to edit, and an older FEAT's to have written.
    for (const kept of [
      null,
      "",
      "{broken",
      "760",
      '{"width":760}',
      '{"width":"760","height":400}',
      '{"width":760.5,"height":400}',
      '{"width":100,"height":400}',
      '{"width":760,"height":100}',
    ]) {
      expect(storedFrameSize(kept, FILLS), String(kept)).toEqual(FILLS)
    }
  })

  it("gives the page's own size where nothing is kept, as the trade review's 384 px", () => {
    // Step 5.9: the trade review's chart stands over its table, 384 px tall until dragged.
    const review = { width: null, height: 384 }

    expect(storedFrameSize(null, review)).toEqual(review)
    expect(storedFrameSize('{"width":null,"height":520}', review)).toEqual({
      width: null,
      height: 520,
    })
  })
})
