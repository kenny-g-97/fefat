import { describe, expect, it } from "vitest"
import type { ChartLook } from "./chart-look"
import {
  type CandleSeries,
  type ChartPane,
  drawnMarker,
  type HistogramSeries,
} from "./drawn-series"
import { ViewWatch, watched } from "./view-watch"

const COLOURS: ChartLook["markers"] = {
  subtle: "#7c7c7c",
  accent: "#fc734d",
  positive: "#10b981",
  negative: "#ff4d6d",
}

function candles(id: string): CandleSeries {
  return {
    kind: "candles",
    id,
    time: [],
    open: [],
    high: [],
    low: [],
    close: [],
  }
}

describe("drawnMarker", () => {
  it("stands a fill's marker at its price, a buy's arrow under it and a sell's above it", () => {
    // Step 5.9: a marker's point is on its fill's price, never above or below its bar.
    const buy = drawnMarker(
      {
        time: 1_772_765_400,
        text: "",
        position: "below",
        shape: "arrowUp",
        tone: "positive",
        price: 6858,
        id: "7/7",
      },
      COLOURS
    )
    const sell = drawnMarker(
      {
        time: 1_772_765_400,
        text: "",
        position: "above",
        shape: "arrowDown",
        tone: "negative",
        price: 6855.25,
      },
      COLOURS
    )

    expect(buy).toEqual({
      time: 1_772_765_400,
      text: "",
      shape: "arrowUp",
      color: "#10b981",
      position: "atPriceBottom",
      price: 6858,
      id: "7/7",
    })
    expect(sell).toMatchObject({ position: "atPriceTop", price: 6855.25 })
    expect(sell).not.toHaveProperty("id")
  })

  it("stands a marker without a price above or below its bar, as a roll's", () => {
    const roll = drawnMarker(
      {
        time: 1_773_007_200,
        text: "ESM2026",
        position: "above",
        shape: "arrowDown",
        tone: "subtle",
      },
      COLOURS
    )

    expect(roll).toMatchObject({ position: "aboveBar", color: "#7c7c7c" })
    expect(roll).not.toHaveProperty("price")
  })
})

describe("watched", () => {
  it("puts the watch among the primitives of the first candle series alone", () => {
    const watch = new ViewWatch(() => undefined)
    const volume: HistogramSeries = {
      kind: "histogram",
      id: "volume",
      time: [],
      value: [],
    }
    const panes: readonly ChartPane[] = [
      { id: "volume", stretch: 1, series: [volume] },
      { id: "price", stretch: 3, series: [candles("price"), candles("other")] },
    ]

    const [first, second] = watched(panes, watch)

    expect(first.series).toEqual([volume])
    expect(
      second.series.map((series) =>
        series.kind === "candles" ? series.primitives : null
      )
    ).toEqual([[watch], undefined])
  })
})
