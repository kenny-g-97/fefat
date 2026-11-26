import { describe, expect, it } from "vitest"
import { NO_BREAK_SPACE } from "@/ui/figures"
import { figureGroups, sideFigure } from "./side-figures"
import { SIDE } from "./side-results.sample"

/** The table's rows, every set in order. */
function rowsOf(perpetual: boolean) {
  return figureGroups(perpetual).flatMap((group) => group.rows)
}

/** Each row's figure of `side` as its cell writes it, by the row's id. */
function writtenRows(
  perpetual: boolean,
  currency: "USD" | "USDT",
  side = SIDE
) {
  return Object.fromEntries(
    rowsOf(perpetual).map((row) => [row.id, sideFigure(side, row, currency)])
  )
}

describe("the figures of a run by side (step 5.22)", () => {
  it("writes each figure in its format, money made or lost in its sign's colour", () => {
    const written = writtenRows(false, "USD")
    expect(written["net-pnl"]).toEqual({ text: "-$1,234.50", look: "negative" })
    expect(written["gross-profit"]).toEqual({
      text: "$2,650.00",
      look: "positive",
    })
    expect(written["gross-loss"]).toEqual({
      text: "-$3,884.50",
      look: "negative",
    })
    expect(written["expectancy"]).toEqual({ text: "-$51.44", look: "negative" })
    expect(written["average-win"]).toEqual({
      text: "$203.85",
      look: "positive",
    })
    expect(written["average-loss"]).toEqual({
      text: "-$388.45",
      look: "negative",
    })
    expect(written["sharpe"]).toEqual({ text: "None", look: "none" })
    const figures = Object.fromEntries(
      Object.entries(written)
        .filter(([, cell]) => cell.look === "figure")
        .map(([id, cell]) => [id, cell.text])
    )
    expect(figures).toEqual({
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
    })
  })

  it("writes money that made nothing in heading text, never signed", () => {
    const even = writtenRows(false, "USD", { ...SIDE, net_pnl: "-0.000000" })
    expect(even["net-pnl"]).toEqual({ text: "$0.00", look: "figure" })
  })

  it("sets the rows in five sets, a perpetual's funding received among the costs", () => {
    expect(figureGroups(false).map((group) => group.id)).toEqual([
      "profit",
      "trades",
      "averages",
      "costs",
      "risk",
    ])
    const ids = (perpetual: boolean) => rowsOf(perpetual).map((row) => row.id)
    expect(ids(false)).not.toContain("funding")
    const costs = figureGroups(true).find((group) => group.id === "costs")
    expect(costs?.rows.map((row) => row.label)).toEqual([
      "Commissions and fees",
      "Funding received",
      "Slippage",
    ])
    const funded = writtenRows(true, "USDT", { ...SIDE, funding: "-12.340000" })
    expect(funded["funding"]).toEqual({
      text: `-12.34${NO_BREAK_SPACE}USDT`,
      look: "negative",
    })
  })

  it("reads None in every row of a side without trades", () => {
    for (const row of rowsOf(true)) {
      expect(sideFigure(null, row, "USD")).toEqual({
        text: "None",
        look: "none",
      })
    }
  })
})
