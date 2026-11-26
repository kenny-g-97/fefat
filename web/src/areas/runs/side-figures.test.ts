import { describe, expect, it } from "vitest"
import { NO_BREAK_SPACE } from "@/ui/figures"
import { figureRows, sideFigure } from "./side-figures"
import { SIDE } from "./side-results.sample"

/** Each row's figure of `side` as its cell writes it, by the row's id. */
function writtenRows(
  perpetual: boolean,
  currency: "USD" | "USDT",
  side = SIDE
) {
  return Object.fromEntries(
    figureRows(perpetual).map((row) => [
      row.id,
      sideFigure(side, row, currency),
    ])
  )
}

describe("the figures of a run by side (step 5.22)", () => {
  it("writes each figure in its format, money made or lost in its sign's colour", () => {
    const written = writtenRows(false, "USD")
    expect(written["net-pnl"]).toEqual({ text: "-$1,234.50", tone: "negative" })
    expect(written["gross-profit"]).toEqual({
      text: "$2,650.00",
      tone: "positive",
    })
    expect(written["gross-loss"]).toEqual({
      text: "-$3,884.50",
      tone: "negative",
    })
    expect(written["expectancy"]).toEqual({ text: "-$51.44", tone: "negative" })
    expect(written["average-win"]).toEqual({
      text: "$203.85",
      tone: "positive",
    })
    expect(written["average-loss"]).toEqual({
      text: "-$388.45",
      tone: "negative",
    })
    const plain = Object.fromEntries(
      Object.entries(written)
        .filter(([, cell]) => cell.tone === undefined)
        .map(([id, cell]) => [id, cell.text])
    )
    expect(plain).toEqual({
      "profit-factor": "0.68",
      trades: "24",
      wins: "13",
      losses: "10",
      "win-rate": "54.17%",
      "trades-per-day": "8.00",
      "expectancy-r": "-0.12 R",
      "win-loss-ratio": "0.52",
      "time-in-market": "1 hour 36 minutes",
      "average-mae": "6.25 ticks",
      "average-mfe": "9.50 ticks",
      fees: "$137.76",
      slippage: "$600.00",
      "max-drawdown": "$2,100.25",
      "longest-spell": "3 days",
      sharpe: "None",
    })
  })

  it("puts a perpetual's funding among the costs, and reads None for a side without trades", () => {
    const ids = (perpetual: boolean) =>
      figureRows(perpetual).map((row) => row.id)
    expect(ids(false)).not.toContain("funding")
    expect(
      ids(true).slice(
        ids(true).indexOf("fees"),
        ids(true).indexOf("slippage") + 1
      )
    ).toEqual(["fees", "funding", "slippage"])
    const funded = writtenRows(true, "USDT", { ...SIDE, funding: "-12.340000" })
    expect(funded["funding"]).toEqual({
      text: `-12.34${NO_BREAK_SPACE}USDT`,
      tone: "negative",
    })
    for (const row of figureRows(true)) {
      expect(sideFigure(null, row, "USD")).toEqual({
        text: "None",
        tone: undefined,
      })
    }
  })
})
