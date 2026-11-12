import { describe, expect, it } from "vitest"
import { decimalsOf, formatCount, formatDecimal, formatPrice } from "./figures"

describe("decimalsOf", () => {
  it("writes each tick, point value, and lot step with the decimals it has", () => {
    const decimals = [0.25, 0.1, 0.01, 0.5, 1, 50, 1.25, 0.00001, 0.005].map(
      decimalsOf
    )

    expect(decimals).toEqual([2, 1, 2, 1, 0, 0, 2, 5, 3])
  })

  it("refuses a value of more places than a figure needs", () => {
    expect(() => decimalsOf(Math.PI)).toThrow(
      "Expected a decimal of at most 9 places, got 3.14159"
    )
  })
})

describe("the formats", () => {
  it("write the API's decimals without a float's noise", () => {
    expect([0.00001, 50, 1.25, 0.1 + 0.2].map(formatDecimal)).toEqual([
      "0.00001",
      "50",
      "1.25",
      "0.3",
    ])
  })

  it("write prices at their instrument's decimals and counts with their thousands apart", () => {
    expect(formatPrice(5012.5, 2)).toBe("5012.50")
    expect(formatPrice(98004.20000000001, 1)).toBe("98004.2")
    expect(formatCount(1234567)).toBe("1,234,567")
  })
})
