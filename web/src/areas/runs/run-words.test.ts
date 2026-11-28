import { describe, expect, it } from "vitest"
import {
  choiceWords,
  foundWords,
  parameterWords,
  resultsLine,
  runDetail,
  runLine,
  tradedWords,
} from "./run-words"

const VERSION = {
  strategy_id: "strategy-1",
  name: "demo",
  version_id: "version-1",
  version: 2,
  instrument: "ES",
  timeframe: "5m",
}

describe("tradedWords", () => {
  it("names what the run trades, whatever its version's code names", () => {
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

describe("runLine", () => {
  const dates = { start: "2026-03-06", end: "2026-03-09" }

  it("names the version, what the run trades, and its dates", () => {
    expect(
      runLine({
        ...dates,
        strategy: VERSION,
        settings: { instrument: "MNQ" },
      })
    ).toBe("Version 2, MNQ in 5m bars, 2026-03-06 to 2026-03-09")
  })

  it("names what a run of no saved version trades, where it knows", () => {
    expect(
      runLine({ ...dates, strategy: null, settings: { instrument: "MNQ" } })
    ).toBe("No saved version, MNQ, 2026-03-06 to 2026-03-09")
    expect(
      runLine({ ...dates, strategy: null, settings: { instrument: null } })
    ).toBe("No saved version, 2026-03-06 to 2026-03-09")
  })
})

describe("resultsLine (step 5.22)", () => {
  const dates = { start: "2026-03-06", end: "2026-03-09" }

  it("names the strategy with its version, what the run trades, and its dates", () => {
    expect(
      resultsLine({
        ...dates,
        strategy: VERSION,
        settings: { instrument: "MNQ" },
      })
    ).toBe("demo version 2, MNQ in 5m bars, 2026-03-06 to 2026-03-09")
    expect(
      resultsLine({ ...dates, strategy: null, settings: { instrument: "ES" } })
    ).toBe("No saved version, ES, 2026-03-06 to 2026-03-09")
  })
})

describe("foundWords", () => {
  const FOUND = "FEAT found this run saved and opened it."

  it("says a cached run was found, under the version launched or an unknown one", () => {
    expect(foundWords({ strategy: VERSION }, true, "version-1")).toBe(FOUND)
    expect(foundWords({ strategy: VERSION }, true, undefined)).toBe(FOUND)
  })

  it("says nothing of a run of the version launched that was not found", () => {
    expect(foundWords({ strategy: VERSION }, false, "version-1")).toBeNull()
    expect(foundWords({ strategy: VERSION }, false, undefined)).toBeNull()
  })

  it("names where the run stands when another version was launched", () => {
    expect(foundWords({ strategy: VERSION }, true, "version-9")).toBe(
      "FEAT found this run saved under demo, version 2, whose code gives the same signals, and opened it."
    )
    expect(foundWords({ strategy: VERSION }, false, "version-9")).toBe(
      "FEAT followed this run under demo, version 2, whose code gives the same signals, rather than run it twice."
    )
    expect(foundWords({ strategy: null }, true, "version-9")).toBe(
      "FEAT found this run saved with no version in the library, whose code gives the same signals, and opened it."
    )
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

describe("choiceWords", () => {
  it("names a run for its checkbox by its version, dates, slippage, and parameters", () => {
    // The design review of step 5.10: a stress's runs differ by their slippage alone.
    const run = {
      strategy: VERSION,
      settings: { instrument: "ES", slippage_ticks: { market: 1, stop: 1 } },
      start: "2026-03-05",
      end: "2026-03-09",
      parameters: { lookback: 12 },
    }

    expect(choiceWords(run)).toBe(
      "demo version 2, ES in 5m bars, 2026-03-05 to 2026-03-09, 1 tick of slippage, lookback 12"
    )
    expect(
      choiceWords({
        ...run,
        settings: { instrument: "ES", slippage_ticks: { market: 2, stop: 3 } },
      })
    ).toBe(
      "demo version 2, ES in 5m bars, 2026-03-05 to 2026-03-09, 2 market and 3 stop ticks of slippage, lookback 12"
    )
  })
})
