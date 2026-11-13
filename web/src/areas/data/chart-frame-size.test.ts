import { describe, expect, it } from "vitest"
import { FILLS } from "@/ui/frame-size"
import { storedFrameSize } from "./chart-frame-size"

describe("storedFrameSize", () => {
  it("reads the size the browser kept, a direction that fills as null", () => {
    expect(storedFrameSize('{"width":760,"height":400}')).toEqual({
      width: 760,
      height: 400,
    })
    expect(storedFrameSize('{"width":null,"height":1600}')).toEqual({
      width: null,
      height: 1600,
    })
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
      '{"width":760,"height":5000}',
    ]) {
      expect(storedFrameSize(kept), String(kept)).toEqual(FILLS)
    }
  })
})
