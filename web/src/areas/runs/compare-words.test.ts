import { describe, expect, it } from "vitest"
import type { ComparedRun } from "@/api/comparisons"
import {
  comparedDetail,
  comparedLabel,
  countChange,
  figureChange,
  moneyChange,
  shareChange,
} from "./compare-words"

function aComparedRun(changes: Partial<ComparedRun>): ComparedRun {
  const figures = {
    pnl: "-2721.560000",
    pnl_share: -0.0544312,
    profit_factor: 0.42,
    expectancy_r: -0.31,
    win_rate: 0.25,
    max_drawdown: "2721.560000",
    max_drawdown_share: 0.0544312,
    sharpe: null,
    trades: 18,
  }
  return {
    run_key: "a".repeat(64),
    strategy: {
      name: "demo",
      version: 2,
      hash: "b".repeat(64),
      parameters: { lookback: 12, stop_atr: 2.0 },
    },
    instrument: "ES",
    timeframe: "5m",
    currency: "USD",
    capital: "50000",
    window: { start: "2026-03-05", end: "2026-03-09" },
    figures,
    deltas: null,
    exit_reasons: {},
    exit_reason_deltas: null,
    curve: { trade_dates: [], shares: [] },
    ...changes,
  }
}

describe("a compared run's words", () => {
  it("names a run by its strategy and version, and tells it apart by what it trades, its dates, and its parameters", () => {
    const run = aComparedRun({})

    expect(comparedLabel(run)).toBe("demo v2")
    expect(comparedDetail(run)).toBe(
      "ES in 5m bars, 2026-03-05 to 2026-03-09, lookback 12, stop_atr 2"
    )
    expect(comparedLabel(aComparedRun({ strategy: null }))).toBe(
      "No saved version"
    )
    expect(comparedDetail(aComparedRun({ strategy: null }))).toBe(
      "ES in 5m bars, 2026-03-05 to 2026-03-09"
    )
  })

  it("signs each change, a zero bare, as the figure would write it", () => {
    // Step 5.10: a change is the API's delta, written as its figure is, with a plus above zero.
    expect(moneyChange("921.560000", "USD")).toBe("+$921.56")
    expect(moneyChange("-12.5", "USD")).toBe("-$12.50")
    expect(moneyChange("0.000000", "USD")).toBe("$0.00")
    expect(countChange(2)).toBe("+2")
    expect(countChange(-1)).toBe("-1")
    expect(countChange(0)).toBe("0")
    expect(shareChange(0.025)).toBe("+2.50%")
    expect(shareChange(-0.0001)).toBe("-0.01%")
    expect(shareChange(0.00001)).toBe("0.00%")
    expect(figureChange(0.314)).toBe("+0.31")
    expect(figureChange(-1.2)).toBe("-1.20")
    expect(figureChange(0.001)).toBe("0.00")
    expect(figureChange(null)).toBe("None")
  })
})
