import { describe, expect, test } from "vitest"
import { tooltipBox } from "./tooltip-place"

const CHART = { width: 960, height: 400 }

describe("a fill's tooltip stands beside its fill, clear of the trade", () => {
  test("an entry's stands before its point, at its price", () => {
    expect(tooltipBox({ ...CHART, x: 500, y: 120 }, true)).toEqual({
      left: 464,
      top: 120,
      transform: "translate(-100%, -50%)",
    })
  })

  test("an entry near the left edge has its tooltip after it", () => {
    expect(tooltipBox({ ...CHART, x: 100, y: 120 }, true)).toEqual({
      left: 136,
      top: 120,
      transform: "translate(0%, -50%)",
    })
  })

  test("any other fill's stands after its point", () => {
    expect(tooltipBox({ ...CHART, x: 500, y: 120 }, false)).toEqual({
      left: 536,
      top: 120,
      transform: "translate(0%, -50%)",
    })
  })

  test("a fill near the right edge has its tooltip before it", () => {
    expect(tooltipBox({ ...CHART, x: 900, y: 120 }, false)).toEqual({
      left: 864,
      top: 120,
      transform: "translate(-100%, -50%)",
    })
  })

  test("near the chart's top or foot the tooltip stays inside it", () => {
    expect(tooltipBox({ ...CHART, x: 500, y: 4 }, true).top).toBe(36)
    expect(tooltipBox({ ...CHART, x: 500, y: 398 }, false).top).toBe(364)
  })
})
