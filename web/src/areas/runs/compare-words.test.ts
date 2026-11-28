import { describe, expect, it } from "vitest"
import type { ComparedRun } from "@/api/comparisons"
import {
  comparedDetails,
  comparedLabel,
  countChange,
  figureChange,
  moneyChange,
  shareChange,
} from "./compare-words"

type Config = ComparedRun["config"]

const CONFIG: Config = {
  capital: "50000",
  contract: null,
  fee_table: "retail-default",
  fidelity: "1m",
  instrument: "ES",
  latency_ms: 100,
  limit_fill: "through",
  provider: "synthetic",
  replay: "skipping",
  roll_handling: "transfer",
  slippage_ticks: { market: 1, stop: 1 },
}

function aComparedRun(
  changes: Partial<ComparedRun>,
  config: Partial<Config> = {}
): ComparedRun {
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
    config: { ...CONFIG, ...config },
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
  it("names a run by its strategy and version, or says it has none", () => {
    expect(comparedLabel(aComparedRun({}))).toBe("demo v2")
    expect(comparedLabel(aComparedRun({ strategy: null }))).toBe(
      "No saved version"
    )
  })

  it("leads each run's line with what it differs by, and leaves out a setting all share", () => {
    // The design review of step 5.10: an ellipsis never cuts what tells two runs apart.
    const first = aComparedRun({
      strategy: {
        name: "demo",
        version: 1,
        hash: "c".repeat(64),
        parameters: { lookback: 12, stop_atr: 1.5 },
      },
    })

    expect(comparedDetails([first, aComparedRun({})])).toEqual([
      "stop_atr 1.5, ES in 5m bars, 2026-03-05 to 2026-03-09, lookback 12",
      "stop_atr 2, ES in 5m bars, 2026-03-05 to 2026-03-09, lookback 12",
    ])
  })

  it("says a stress's slippage, the one thing its runs differ by", () => {
    const base = aComparedRun({})
    const stressed = aComparedRun(
      {},
      { slippage_ticks: { market: 2, stop: 2 } }
    )
    const split = aComparedRun({}, { slippage_ticks: { market: 2, stop: 3 } })

    expect(
      comparedDetails([base, stressed, split]).map(
        (line) => line.split(", ")[0]
      )
    ).toEqual([
      "1 tick of slippage",
      "2 ticks of slippage",
      "2 market and 3 stop ticks of slippage",
    ])
  })

  it("names a notebook's run by what it trades and its dates, and TBBO as an acronym", () => {
    const notebook = aComparedRun({ strategy: null }, { fidelity: "tbbo" })

    expect(comparedDetails([notebook, aComparedRun({})])).toEqual([
      "filled on TBBO, ES in 5m bars, 2026-03-05 to 2026-03-09",
      "lookback 12, stop_atr 2, filled on 1-minute bars, ES in 5m bars, 2026-03-05 to 2026-03-09",
    ])
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
