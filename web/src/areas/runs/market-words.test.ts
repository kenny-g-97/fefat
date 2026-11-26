import { describe, expect, it } from "vitest"
import type { DaysExposure } from "@/api/run-results"
import {
  buyAndHoldLabel,
  buyAndHoldNote,
  exposureDetail,
  lotsWords,
  sidesWords,
} from "./market-words"

const COUNTED: DaysExposure = {
  days: 9,
  correlation: 0.8123,
  beta_lots: 0.9049,
  uncounted: null,
}

describe("a market exposure's words", () => {
  it("names the days a figure counts, or why it reads None", () => {
    // Step 5.23: each stat names its days, and a figure with nothing to count says why.
    expect(exposureDetail(0.81, COUNTED)).toBe("Over 9 days")
    expect(exposureDetail(0.81, { ...COUNTED, days: 1 })).toBe("Over 1 day")
    expect(exposureDetail(null, { days: 2, uncounted: "too_few_days" })).toBe(
      "Needs 3 days"
    )
    expect(
      exposureDetail(null, { days: 9, uncounted: "market_never_differed" })
    ).toBe("The market's days never differed")
  })

  it("counts a beta of no lots where the run's days never differed", () => {
    // A run that never trades has no correlation, while its beta is counted, at zero.
    const flat = { days: 13, uncounted: "run_never_differed" } as const

    expect(exposureDetail(null, flat)).toBe("The run's days never differed")
    expect(exposureDetail(0, flat)).toBe("Over 13 days")
  })

  it("refuses a figure that reads None without a reason", () => {
    expect(() => exposureDetail(null, { days: 9, uncounted: null })).toThrow(
      "Expected why a figure over 9 days reads None, got no reason."
    )
  })

  it("says the falling and the rising days' figures, or why they read None", () => {
    const rising: DaysExposure = {
      days: 2,
      correlation: null,
      beta_lots: null,
      uncounted: "too_few_days",
    }

    // The design review: each side on a line of its own, falling above rising.
    expect(sidesWords(COUNTED, rising)).toBe(
      "Over the 9 days the market fell: correlation 0.81, beta 0.90 lots.\nOver the 2 days the market rose: correlation None, beta None, needs 3 days."
    )
    const still: DaysExposure = { ...rising, days: 0 }
    const flat: DaysExposure = {
      days: 4,
      correlation: null,
      beta_lots: 0,
      uncounted: "run_never_differed",
    }
    expect(sidesWords(flat, still)).toBe(
      "Over the 4 days the market fell: correlation None, beta 0.00 lots, the run's days never differed.\nThe market rose on no day."
    )
  })

  it("names buy and hold by its lots, and says what its size keeps or why it has none", () => {
    expect(buyAndHoldLabel(0.4925)).toBe("Buy and hold, 0.49 lots")
    expect(lotsWords(1.25)).toBe("1.25 lots")
    expect(buyAndHoldNote(null)).toBe(
      "Buy and hold buys at the run's first mark and holds to its last, paying no fee, slippage, or funding. At the run's volatility it holds the lots whose days move as much as the run's; its Sharpe and its spell under a peak stay one lot's."
    )
    expect(buyAndHoldNote("too_few_days")).toBe(
      "Buy and hold buys at the run's first mark and holds to its last, paying no fee, slippage, or funding. At the run's volatility it reads None: needs 3 days."
    )
  })
})
