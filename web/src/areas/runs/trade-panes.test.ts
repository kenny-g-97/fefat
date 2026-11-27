import { describe, expect, it } from "vitest"
import type { ChartFill, ChartTrade, ChartWindow } from "@/api/run-chart"
import { TradeOverlay } from "@/charts/trade-overlay"
import {
  barPlaces,
  drawnFills,
  overlayView,
  tooltipFill,
  tradePanes,
} from "./trade-panes"

const COLOURS = {
  subtle: "#7c7c7c",
  accent: "#fc734d",
  positive: "#10b981",
  negative: "#ff4d6d",
}
const OPENS = [1_000, 1_300, 1_600, 1_900]

function fill(
  order: number,
  side: "buy" | "sell",
  barTime: number | null,
  price: string
): ChartFill {
  return {
    order,
    role: side === "buy" ? "entry" : "stop",
    side,
    lots: 1,
    time: "2026-03-06T02:50:11Z",
    bar_time: barTime,
    price,
    fidelity: "trades",
  }
}

function trade(
  row: number,
  fills: readonly ChartFill[],
  pnl: string,
  stop: Readonly<{ first: string | null; last: string | null }>
): ChartTrade {
  return {
    trade: row,
    entry_order: 3 * row + 1,
    side: "long",
    lots: 1,
    pnl,
    fills: [...fills],
    stop,
    targets: ["6862", "6866"],
  }
}

const LOSER = trade(
  2,
  [fill(7, "buy", 1_300, "6858"), fill(8, "sell", 1_600, "6855.25")],
  "-118.240000",
  { first: "6856", last: "6857" }
)
const OPEN_ENDED = trade(
  3,
  [fill(10, "buy", 1_900, "6860"), fill(11, "sell", null, "6863")],
  "42.500000",
  { first: "6858", last: "6858" }
)

const CHART: ChartWindow = {
  bars: {
    time: OPENS,
    trade_date: OPENS.map(() => "2026-03-06"),
    open: OPENS.map(() => 6858),
    high: OPENS.map(() => 6860),
    low: OPENS.map(() => 6855),
    close: OPENS.map(() => 6858.5),
    volume: OPENS.map(() => 10),
    contract: OPENS.map(() => "ESH2026"),
  },
  features: [
    { name: "highest", unit: "as_stored", values: [null, 1, 2, 3] },
    { name: "atr", unit: "price", values: [null, 1.25, 1.5, 1.75] },
  ],
  trades: [LOSER, OPEN_ENDED],
  tickSize: "0.25",
  warnings: [],
}

const FILLS = drawnFills(CHART, barPlaces(CHART.bars, false))

describe("the trade review's panes", () => {
  it("marks every fill on the bars at its price, a buy under it and a sell over it", () => {
    // Step 5.9: markers use the fill's own time and price, from the fills ledger.
    const [price] = tradePanes(CHART, "5m", true, FILLS, {
      selected: 2,
      overlay: new TradeOverlay(),
    })
    const candles = price.series[0]
    if (candles.kind !== "candles") {
      throw new Error("Expected the candles first.")
    }

    expect(candles.markers).toEqual([
      expect.objectContaining({
        time: 1_300,
        price: 6858,
        position: "below",
        shape: "arrowUp",
        tone: "positive",
        id: "7/0",
        size: 2,
      }),
      expect.objectContaining({
        time: 1_600,
        price: 6855.25,
        position: "above",
        shape: "arrowDown",
        tone: "negative",
        id: "7/1",
        size: 2,
      }),
      expect.not.objectContaining({ size: 2 }),
    ])
    expect(candles.primitives).toHaveLength(1)
  })

  it("draws the price over the volume and a pane a feature, its values beside the bars", () => {
    const panes = tradePanes(CHART, "5m", true, FILLS, {
      selected: null,
      overlay: new TradeOverlay(),
    })

    expect(panes.map((pane) => [pane.id, pane.stretch])).toEqual([
      ["price", 3],
      ["volume", 1],
      ["feature-highest", 1],
      ["feature-atr", 1],
    ])
    expect(panes[3]?.series[0]).toEqual({
      kind: "line",
      id: "feature-atr",
      time: OPENS,
      value: [null, 1.25, 1.5, 1.75],
    })
  })

  it("places a daily bar's fill on its trade date, as the chart places the bar", () => {
    const daily = drawnFills(CHART, barPlaces(CHART.bars, true))

    expect(daily.get("7/0")?.time).toBe("2026-03-06")
  })
})

describe("overlayView", () => {
  it("joins each trade's first fill to its last in its result's colour, solid when selected", () => {
    const view = overlayView(CHART, FILLS, 2, COLOURS)

    expect(view.connectors).toEqual([
      {
        from: { time: 1_300, price: 6858 },
        to: { time: 1_600, price: 6855.25 },
        colour: COLOURS.negative,
        selected: true,
      },
    ])
  })

  it("bands the selected trade from its entry to its stop and to its furthest target", () => {
    const view = overlayView(CHART, FILLS, 2, COLOURS)

    expect(view.bands).toEqual([
      {
        from: 1_300,
        to: 1_600,
        low: 6856,
        high: 6858,
        colour: "rgba(255, 77, 109, 0.12)",
      },
      {
        from: 1_300,
        to: 1_600,
        low: 6858,
        high: 6866,
        colour: "rgba(16, 185, 129, 0.12)",
      },
    ])
    expect(view.levels).toEqual([
      { from: 1_300, to: 1_600, price: 6857, colour: COLOURS.negative },
    ])
  })

  it("draws nothing of a trade whose exit lies off the bars read, nor bands unselected", () => {
    expect(overlayView(CHART, FILLS, 3, COLOURS)).toEqual({
      connectors: [expect.objectContaining({ selected: false })],
      bands: [],
      levels: [],
    })
  })
})

describe("tooltipFill", () => {
  it("names the marker under the pointer, else a fill on the crosshair's bar, else the entry", () => {
    const hovered = tooltipFill(CHART, FILLS, 2, {
      hovered: "7/1",
      crosshair: null,
    })
    const onTheBar = tooltipFill(CHART, FILLS, 2, {
      hovered: null,
      crosshair: 3,
    })
    const pinned = tooltipFill(CHART, FILLS, 2, {
      hovered: null,
      crosshair: 0,
    })

    expect([hovered?.drawn.id, hovered?.pinned]).toEqual(["7/1", false])
    expect([onTheBar?.drawn.id, onTheBar?.pinned]).toEqual(["10/0", false])
    expect([pinned?.drawn.id, pinned?.pinned]).toEqual(["7/0", true])
    expect(
      tooltipFill(CHART, FILLS, null, { hovered: null, crosshair: 0 })
    ).toBe(null)
  })
})
