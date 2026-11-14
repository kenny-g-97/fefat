import { describe, expect, it } from "vitest"
import { chartSearch } from "./chart-search"

describe("chartSearch", () => {
  it("takes every root and contract the store can name, as its folders do", () => {
    // Step 5.4's engine review: a root such as `mnq_c` was read as none, and the page charted
    // another root in its place.
    for (const name of ["MES", "BTCUSDT-PERP", "mnq_c", "BTC.P", "MESM2026"]) {
      expect(chartSearch.parse({ instrument: name, contract: name })).toEqual({
        instrument: name,
        contract: name,
        timeframe: "5m",
        prices: "adjusted",
      })
    }
  })

  it("reads what it cannot take as its default", () => {
    expect(
      chartSearch.parse({
        instrument: "../MES",
        contract: "MES alone",
        timeframe: "2m",
        prices: "settled",
        provider: "data bento",
      })
    ).toEqual({ timeframe: "5m", prices: "adjusted" })
  })
})
