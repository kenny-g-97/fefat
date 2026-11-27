import { describe, expect, it } from "vitest"
import type { BarColumns } from "./bar-windows"
import {
  type ChartFill,
  type ChartTrade,
  type ChartWindow,
  joinedWindows,
  mergedTrades,
} from "./run-chart"

function bars(...times: number[]): BarColumns {
  return {
    time: times,
    trade_date: times.map(() => "2026-03-06"),
    open: times.map(() => 6858),
    high: times.map(() => 6859),
    low: times.map(() => 6857),
    close: times.map(() => 6858.5),
    volume: times.map(() => 10),
    contract: times.map(() => "ESH2026"),
  }
}

function fill(order: number, barTime: number | null): ChartFill {
  return {
    order,
    role: order === 7 ? "entry" : "stop",
    side: order === 7 ? "buy" : "sell",
    lots: 1,
    time: "2026-03-06T02:50:11.668134794Z",
    bar_time: barTime,
    price: "6858",
    fidelity: "trades",
  }
}

function trade(row: number, fills: readonly ChartFill[]): ChartTrade {
  return {
    trade: row,
    entry_order: 3 * row + 1,
    side: "long",
    lots: 1,
    pnl: "-118.240000",
    fills: [...fills],
    stop: { first: "6856", last: "6856" },
    targets: ["6862"],
  }
}

function window(
  times: readonly number[],
  trades: readonly ChartTrade[],
  atr: readonly (number | null)[]
): ChartWindow {
  return {
    bars: bars(...times),
    features: [{ name: "atr", unit: "price", values: [...atr] }],
    trades,
    tickSize: "0.25",
    warnings: ["The fee table charges a default."],
  }
}

describe("joinedWindows", () => {
  it("joins windows newest first into one oldest first, each feature beside its bars", () => {
    // Step 5.9: the chart draws the windows read in a row as one series.
    const newer = window([300, 600], [], [1.5, 1.75])
    const older = window([0], [], [null])

    const joined = joinedWindows([newer, older])

    expect(joined.bars.time).toEqual([0, 300, 600])
    expect(joined.features).toEqual([
      { name: "atr", unit: "price", values: [null, 1.5, 1.75] },
    ])
    expect(joined.warnings).toEqual(["The fee table charges a default."])
  })
})

describe("mergedTrades", () => {
  it("keeps a trade two windows show once, each fill on the bar either window gives it", () => {
    // A trade entered in one window and left in the next: each window sends every fill, the bar
    // only for the fills on its own bars.
    const entered = trade(2, [fill(7, 100), fill(8, null)])
    const left = trade(2, [fill(7, null), fill(8, 900)])
    const another = trade(1, [fill(4, 50)])

    const merged = mergedTrades([entered, another, left])

    expect(merged.map((each) => each.trade)).toEqual([1, 2])
    expect(merged[1]?.fills.map((each) => each.bar_time)).toEqual([100, 900])
  })
})
