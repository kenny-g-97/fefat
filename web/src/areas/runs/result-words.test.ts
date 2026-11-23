import { describe, expect, it } from "vitest"
import {
  hourLabel,
  sampleSizeWords,
  sentenceCase,
  signed,
} from "./result-words"

describe("the words of a run's results", () => {
  it("writes the API's words in sentence case", () => {
    expect(sentenceCase("target_1")).toBe("Target 1")
    expect(sentenceCase("risk_management")).toBe("Risk management")
    expect(sentenceCase("monday")).toBe("Monday")
    expect(sentenceCase("roll_open_interest")).toBe("Roll open interest")
  })

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
})
