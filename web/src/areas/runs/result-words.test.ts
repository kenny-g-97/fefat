import { describe, expect, it } from "vitest"
import {
  hourLabel,
  monteCarloNote,
  sampleSizeWords,
  signed,
  toneOf,
} from "./result-words"

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
})
