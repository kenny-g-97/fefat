import { describe, expect, it } from "vitest"
import { keyAction } from "./chart-keys"
import { rollMarks, sessionSpans } from "./chart-marks"

describe("sessionSpans", () => {
  it("shades every other session counting back from the newest, which is not", () => {
    const spans = sessionSpans(
      [1, 2, 3, 4, 5, 6],
      [
        "2026-03-05",
        "2026-03-05",
        "2026-03-06",
        "2026-03-09",
        "2026-03-09",
        "2026-03-09",
      ]
    )

    expect(spans).toEqual([
      { first: 1, last: 2, shaded: false },
      { first: 3, last: 3, shaded: true },
      { first: 4, last: 6, shaded: false },
    ])
  })

  it("keeps each session's shade when older bars arrive", () => {
    const now = sessionSpans([3, 4], ["2026-03-06", "2026-03-09"])
    const later = sessionSpans(
      [1, 2, 3, 4],
      ["2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09"]
    )

    expect(later.slice(-2)).toEqual(now)
  })
})

describe("rollMarks", () => {
  it("marks the first bar of each new contract of a spliced series, across any window's edge", () => {
    const marks = rollMarks(
      [1, 2, 3, 4],
      ["MESH2026", "MESH2026", "MESM2026", "MESM2026"]
    )

    expect(marks).toEqual([
      {
        time: 3,
        text: "MESM2026",
        position: "above",
        shape: "arrowDown",
        tone: "subtle",
      },
    ])
    expect(rollMarks([1, 2], ["MESM2026", "MESM2026"])).toEqual([])
  })
})

describe("keyAction", () => {
  it("pans, zooms, and goes to either end, and leaves other keys to the page", () => {
    expect(
      ["ArrowLeft", "PageDown", "Home", "End", "+", "-", "Tab"].map(keyAction)
    ).toEqual([
      { kind: "pan", screens: -0.1 },
      { kind: "pan", screens: 1 },
      { kind: "earliest" },
      { kind: "latest" },
      { kind: "zoom", factor: 1.25 },
      { kind: "zoom", factor: 0.8 },
      undefined,
    ])
  })
})
