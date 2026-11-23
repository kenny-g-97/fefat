import { describe, expect, it } from "vitest"
import {
  counted,
  decimalsOf,
  fidelityLabel,
  formatAligned,
  formatCount,
  formatDecimal,
  formatEdge,
  formatFigure,
  formatMoney,
  formatPrice,
  formatShare,
  moneySign,
} from "./figures"

describe("the results' figures (step 5.7)", () => {
  it("writes a ratio or an amount at two decimals with its thousands apart", () => {
    expect(formatFigure(1.8391)).toBe("1.84")
    expect(formatFigure(-0.314)).toBe("-0.31")
    expect(formatFigure(51250.5)).toBe("51,250.50")
  })

  it("writes no sign on a value that rounds to zero", () => {
    expect(formatFigure(-0.001)).toBe("0.00")
    expect(formatShare(-0.00001)).toBe("0.00%")
  })

  it("writes a share in percent", () => {
    expect(formatShare(0.025)).toBe("2.50%")
    expect(formatShare(0.5417)).toBe("54.17%")
    expect(formatShare(-0.0166)).toBe("-1.66%")
  })

  it("writes a histogram's edge with the decimals it holds", () => {
    expect(formatEdge(-1.5)).toBe("-1.5")
    expect(formatEdge(0.29)).toBe("0.29")
    expect(formatEdge(12500)).toBe("12,500")
    expect(formatEdge(0)).toBe("0")
  })
})

describe("formatAligned", () => {
  it("lines up a column's decimal points with spaces, adding no digit", () => {
    // Step 5.4's design review: GC's tick of 0.1 sat a place to the right of CL's 0.01.
    expect([0.01, 0.1, 0.25].map((each) => formatAligned(each, 2))).toEqual([
      "0.01",
      "0.1 ",
      "0.25",
    ])
    expect([0.00001, 0.001, 1].map((each) => formatAligned(each, 5))).toEqual([
      "0.00001",
      "0.001  ",
      "1      ",
    ])
    expect(formatAligned(50, 0)).toBe("50")
    expect(() => formatAligned(0.25, 1)).toThrow(
      "Expected a decimal of at most 1 places, got 0.25."
    )
  })
})

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

  it("count a noun in its singular for one alone", () => {
    expect([0, 1, 2760].map((count) => counted(count, "record"))).toEqual([
      "0 records",
      "1 record",
      "2,760 records",
    ])
    expect(counted(3, "mismatch", "mismatches")).toBe("3 mismatches")
  })
})

describe("formatMoney", () => {
  it("writes the API's decimal text with its thousands apart and no float between", () => {
    expect(formatMoney("-2721.560000")).toBe("-2,721.56")
    expect(formatMoney("1250")).toBe("1,250.00")
    expect(formatMoney("0.000000")).toBe("0.00")
    expect(formatMoney("999.5")).toBe("999.50")
    // A float would round this one; the text keeps every digit the API sends.
    expect(formatMoney("12345678901234.125000")).toBe("12,345,678,901,234.125")
  })

  it("reads a sum's sign from its text", () => {
    expect(
      ["-2721.560000", "0.010000", "0.000000", "-0.000000", "0"].map(moneySign)
    ).toEqual(["negative", "positive", "zero", "zero", "zero"])
  })

  it("refuses what is no decimal", () => {
    expect(() => formatMoney("twelve")).toThrow(
      'Expected money as decimal text, got "twelve".'
    )
  })
})

describe("fidelityLabel", () => {
  it("says what a dataset holds in words, and refuses a fidelity the API never sends", () => {
    expect(
      ["trades", "tbbo", "1m", "1s", "5m", "1d"].map(fidelityLabel)
    ).toEqual([
      "Trades",
      "TBBO",
      "1-minute bars",
      "1-second bars",
      "5-minute bars",
      "1-day bars",
    ])
    expect(() => fidelityLabel("weekly")).toThrow(
      'Expected a fidelity such as trades or 1m, got "weekly".'
    )
  })
})
