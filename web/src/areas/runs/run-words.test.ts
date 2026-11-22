import { describe, expect, it } from "vitest"
import { parameterWords, runDetail, tradedWords } from "./run-words"

const VERSION = {
  strategy_id: "strategy-1",
  name: "demo",
  version_id: "version-1",
  version: 2,
  instrument: "MNQ",
  timeframe: "5m",
}

describe("tradedWords", () => {
  it("names the instrument and the bars of a run of a saved version", () => {
    expect(
      tradedWords({ strategy: VERSION, settings: { instrument: "MNQ" } })
    ).toBe("MNQ in 5m bars")
  })

  it("names the instrument alone for a run of no saved version", () => {
    expect(
      tradedWords({ strategy: null, settings: { instrument: "ES" } })
    ).toBe("ES")
  })

  it("is empty for a notebook's run saved before a run named its instrument", () => {
    expect(
      tradedWords({ strategy: null, settings: { instrument: null } })
    ).toBe("")
  })
})

describe("runDetail", () => {
  it("names what a run trades, then its parameters", () => {
    expect(
      runDetail({
        strategy: VERSION,
        settings: { instrument: "MNQ" },
        parameters: { lookback: 12, stop_atr: 1.5 },
      })
    ).toBe("MNQ in 5m bars, lookback 12, stop_atr 1.5")
  })

  it("leaves out what a run does not name", () => {
    expect(
      runDetail({
        strategy: VERSION,
        settings: { instrument: "MNQ" },
        parameters: {},
      })
    ).toBe("MNQ in 5m bars")
    expect(
      runDetail({
        strategy: null,
        settings: { instrument: null },
        parameters: {},
      })
    ).toBe("")
  })
})

describe("parameterWords", () => {
  it("names each parameter with its value, a nested one as its JSON", () => {
    expect(
      parameterWords({
        parameters: {
          lookback: 12,
          on: true,
          filter: { kind: "atr", length: 14 },
          levels: [1, 2],
          none: null,
        },
      })
    ).toBe(
      'lookback 12, on true, filter {"kind":"atr","length":14}, levels [1,2], none null'
    )
  })

  it("is empty for a run that names none", () => {
    expect(parameterWords({ parameters: {} })).toBe("")
  })
})
