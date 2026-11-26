import { describe, expect, it } from "vitest"
import { picked } from "@/ui/choices"
import { NO_BREAK_SPACE } from "@/ui/figures"
import {
  hourLabel,
  MONTE_CARLO_CHARTS,
  monteCarloNote,
  pathFigureTone,
  pathFigureWritten,
  percentWords,
  sampleSizeWords,
  sidesNote,
  signed,
  toneOf,
} from "./result-words"
import { SIDE } from "./side-results.sample"

describe("the words of a run's results", () => {
  it("writes an hour of the day with its minutes", () => {
    expect(hourLabel("9")).toBe("09:00")
    expect(hourLabel("23")).toBe("23:00")
    expect(hourLabel("0")).toBe("00:00")
  })

  it("says which of the counts a sample needs the run reaches", () => {
    expect(sampleSizeWords("below_minimum", 1)).toBe(
      "1 trade, under the 30 a sample needs at the least"
    )
    expect(sampleSizeWords("minimum", 45)).toBe(
      "45 trades, past the minimum of 30, under the 100 preferred"
    )
    expect(sampleSizeWords("preferred", 120)).toBe(
      "120 trades, past the 100 preferred, under the 200 of high confidence"
    )
    expect(sampleSizeWords("high_confidence", 1234)).toBe(
      "1,234 trades, past the 200 of high confidence"
    )
  })

  it("writes a change with its sign", () => {
    expect(signed("12.75", "positive")).toBe("+12.75")
    expect(signed("-59.50", "negative")).toBe("-59.50")
    expect(signed("0.00", "zero")).toBe("0.00")
  })

  it("tones money by its sign, and a zero not at all", () => {
    expect(toneOf("12.500000")).toBe("positive")
    expect(toneOf("-0.010000")).toBe("negative")
    expect(toneOf("0.000000")).toBeUndefined()
  })

  it("says what a Monte Carlo drew and what its paths cannot show", () => {
    // Step 5.20: how many paths of how many trades, from which seed, of closed trades, no streak.
    expect(monteCarloNote({ paths: 1000, trades: 24, seed: 0 })).toBe(
      "1,000 paths of 24 trades, drawn with replacement from seed 0. Drawdowns are of closed trades, and a path keeps no streak across days."
    )
    expect(monteCarloNote({ paths: 100, trades: 2, seed: 12345 })).toContain(
      "100 paths of 2 trades, drawn with replacement from seed 12345."
    )
  })

  it("names each chart the Monte Carlo card offers, and refuses another", () => {
    // Step 5.21: the select's words, in the prompt's order.
    expect(MONTE_CARLO_CHARTS.map((chart) => chart.label)).toEqual([
      "Equity",
      "Net P&L",
      "Max drawdown",
      "Profit factor",
      "Avg. MAE",
      "Avg. MFE",
    ])
    expect(picked(MONTE_CARLO_CHARTS, "max_drawdown")).toBe("max_drawdown")
    expect(() => picked(MONTE_CARLO_CHARTS, "sharpe")).toThrow(/got sharpe\./)
  })

  it("tones the paths' net P&L by its sign, and no other figure", () => {
    // The design review: every net P&L on the page stands in its sign's colour.
    expect(pathFigureTone("net_pnl", -2721.56)).toBe("negative")
    expect(pathFigureTone("net_pnl", 480)).toBe("positive")
    expect(pathFigureTone("net_pnl", 0)).toBeUndefined()
    // The design review's second round: -0.004 reads "$0.00", whose minus the page drops.
    expect(pathFigureTone("net_pnl", -0.004)).toBeUndefined()
    expect(pathFigureWritten("net_pnl", -0.004, "USD")).toBe("$0.00")
    expect(pathFigureTone("net_pnl", -0.005)).toBe("negative")
    expect(pathFigureTone("max_drawdown", 2721.56)).toBeUndefined()
    expect(pathFigureTone("profit_factor", null)).toBeUndefined()
  })

  it("writes a figure of the paths as the page writes money, ticks, and a profit factor", () => {
    // D-117 for money, the KPI cards for a profit factor, and ticks at two decimals.
    expect(pathFigureWritten("max_drawdown", 3688.78, "USD")).toBe("$3,688.78")
    expect(pathFigureWritten("net_pnl", -1250.5, "USDT")).toBe(
      `-1,250.50${NO_BREAK_SPACE}USDT`
    )
    expect(pathFigureWritten("profit_factor", 1.8366, "USD")).toBe("1.84")
    expect(pathFigureWritten("average_mae_ticks", 12.3456, "USD")).toBe(
      "12.35 ticks"
    )
    expect(pathFigureWritten("profit_factor", null, "USD")).toBe("None")
  })

  it("says where the paths stand at a percent, and why a path has no profit factor", () => {
    expect(percentWords("max_drawdown", 95, 3688.78)).toBe(
      "95% of paths at or under this max drawdown"
    )
    expect(percentWords("net_pnl", 0, -12)).toBe(
      "0% of paths at or under this net P&L"
    )
    expect(percentWords("average_mfe_ticks", 50, 18.5)).toBe(
      "50% of paths at or under this average MFE"
    )
    expect(percentWords("profit_factor", 98, null)).toBe(
      "The path at 98% drew no losing trade, so it has no profit factor"
    )
  })
})

describe("sidesNote (step 5.22)", () => {
  const closed =
    "A side's max drawdown, longest spell under a peak, and Sharpe are of its closed trades, walked from the capital in the order they closed; those of all trades mark open trades to market."
  const side = SIDE

  it("says a side's risk is of its closed trades, and which side made no trade", () => {
    expect(sidesNote({ long: side, short: side })).toBe(closed)
    expect(sidesNote({ long: side, short: null })).toBe(
      `${closed} This run made no short trade, so its column reads None.`
    )
    expect(sidesNote({ long: null, short: side })).toBe(
      `${closed} This run made no long trade, so its column reads None.`
    )
    expect(sidesNote({ long: null, short: null })).toBe(
      `${closed} This run made no trade, so both sides read None.`
    )
  })
})
