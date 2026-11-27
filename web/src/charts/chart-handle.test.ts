import { describe, expect, it } from "vitest"
import { keptView } from "./chart-handle"
import { movedCrosshair } from "./chart-steps"

type Span = Readonly<{ from: number; to: number }>

/** A chart whose view holds the bars `from` to `to`, and the views set on it. */
function chartViewing(from: number, to: number) {
  const set: Span[] = []
  const chart = {
    timeScale: () => ({
      getVisibleLogicalRange: () => ({ from, to }),
      setVisibleLogicalRange: (range: Span) => {
        set.push(range)
      },
    }),
  }
  return { chart, set }
}

describe("keptView", () => {
  it("keeps the bars in view as older ones arrive, and says how many came before", () => {
    // Step 5.9's code review: the bars a crosshair counts move too, so the view's answer says
    // by how much.
    const { chart, set } = chartViewing(10, 90)

    const kept = keptView(chart, [300, 400, 500])([100, 200, 300, 400, 500])

    expect(kept).toBe(2)
    expect(set).toEqual([{ from: 12, to: 92 }])
  })

  it("keeps the view as newer bars arrive after the first", () => {
    const { chart, set } = chartViewing(10, 90)

    expect(keptView(chart, [300, 400])([300, 400, 500])).toBe(0)
    expect(set).toEqual([{ from: 10, to: 90 }])
  })

  it("says none where its first bar is gone, and moves nothing, nor where it held none", () => {
    const { chart, set } = chartViewing(10, 90)

    expect(keptView(chart, [300, 400])([400, 500])).toBeNull()
    expect(keptView(chart, undefined)([400, 500])).toBe(0)
    expect(set).toEqual([])
  })
})

describe("movedCrosshair", () => {
  it("stands on the same bar once bars arrive before it, and on none once its bars are gone", () => {
    expect(movedCrosshair(5, 3)).toBe(8)
    expect(movedCrosshair(5, 0)).toBe(5)
    expect(movedCrosshair(5, null)).toBeNull()
    expect(movedCrosshair(null, 3)).toBeNull()
  })
})
