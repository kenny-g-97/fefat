import { describe, expect, it } from "vitest"
import type { RunEstimated } from "@/api/runs"
import {
  estimateAsked,
  feeTableOf,
  instrumentChoices,
  instrumentChosen,
  isTradeDate,
  readWords,
  runReadiness,
  shownDates,
  ticksRefusal,
  tradeDateRefusal,
  UNTOUCHED,
  windowRefusal,
} from "./run-draft"

const HELD = { start: "2026-03-06", end: "2026-03-09" }

const ESTIMATE: RunEstimated = {
  state: "estimated",
  instrument: "ES",
  timeframe: "5m",
  instruments: ["ES", "MES"],
  providers: ["synthetic"],
  contracts: ["ESH2026", "ESM2026"],
  levels: ["1m"],
  fee_tables: ["retail-default", "prop-topstep"],
  settings: {
    fidelity: "1m",
    latency_ms: 100,
    slippage_ticks: { market: 1, stop: 1 },
    limit_fill: "through",
    roll_handling: "transfer",
    fee_table: "retail-default",
    capital: "50000",
    replay: "skipping",
    provider: "synthetic",
    contract: null,
  },
  held: HELD,
  window: HELD,
  sessions: 2,
  bars: 2760,
  ticks: 0,
}

/** The settings the dialog does not offer, sent as the estimate applied them. */
const THE_RUNS_OWN = {
  latency_ms: 100,
  limit_fill: "through",
  roll_handling: "transfer",
  capital: "50000",
  replay: "skipping",
}

describe("trade dates", () => {
  it("reads a date from the calendar's rule, without the browser's clock", () => {
    expect(["2026-03-06", "2024-02-29"].map(isTradeDate)).toEqual([true, true])
    expect(
      ["2026-02-29", "2026-13-01", "2026-04-31", "6/3/2026", "2026-3-6"].map(
        isTradeDate
      )
    ).toEqual([false, false, false, false, false])
  })

  it("refuses a date outside the data held and a window that ends before it starts", () => {
    expect(tradeDateRefusal("2026-03-06", HELD)).toBeNull()
    expect(tradeDateRefusal("soon", HELD)).toBe(
      "Type a date such as 2026-03-06."
    )
    expect(tradeDateRefusal("2026-03-05", HELD)).toBe(
      "Choose a date from 2026-03-06 to 2026-03-09, the data this run reads."
    )
    expect(windowRefusal("2026-03-09", "2026-03-06")).toBe(
      "Choose an end on or after 2026-03-09."
    )
    expect(windowRefusal("2026-03-06", "2026-03-06")).toBeNull()
  })
})

describe("ticksRefusal", () => {
  it("takes whole ticks alone", () => {
    expect(["0", "1", "1000"].map(ticksRefusal)).toEqual([null, null, null])
    expect(ticksRefusal("1.5")).toBe("Type a whole number of ticks, such as 1.")
    expect(ticksRefusal("1001")).toBe(
      "Type a whole number of ticks, such as 1."
    )
    expect(ticksRefusal("")).toBe("Type a whole number of ticks, such as 1.")
  })
})

describe("estimateAsked", () => {
  it("asks for the run's defaults and leaves a date out until it is one", () => {
    expect(estimateAsked("v1", UNTOUCHED)).toEqual({
      strategy_version_id: "v1",
      settings: {},
    })
    expect(
      estimateAsked("v1", {
        ...UNTOUCHED,
        provider: "synthetic",
        contract: "ESH2026",
        fidelity: "1m",
        from: "2026-03-06",
        to: "not yet",
      })
    ).toEqual({
      strategy_version_id: "v1",
      start: "2026-03-06",
      settings: { provider: "synthetic", contract: "ESH2026", fidelity: "1m" },
    })
  })
})

describe("the instrument a run trades", () => {
  it("is asked of the estimate and sent with the run once chosen", () => {
    const moved = { ...UNTOUCHED, instrument: "MES" }

    expect(estimateAsked("v1", moved).settings).toEqual({ instrument: "MES" })
    const ready = runReadiness("v1", moved, ESTIMATE, true)
    const plain = runReadiness("v1", UNTOUCHED, ESTIMATE, true)
    expect(ready.kind === "ready" && ready.request.settings?.instrument).toBe(
      "MES"
    )
    expect(plain.kind === "ready" && plain.request.settings).not.toHaveProperty(
      "instrument"
    )
  })

  it("sets what the data decides back, and keeps the dates and the ticks", () => {
    const draft = {
      ...UNTOUCHED,
      provider: "vendor",
      contract: "ESH2026",
      fidelity: "1m",
      feeTable: "prop-topstep",
      from: "2026-03-06",
      to: "2026-03-09",
      slippage: { market: "2", stop: null },
    }

    expect(instrumentChosen(draft, "MES", "ES")).toEqual({
      ...draft,
      instrument: "MES",
      provider: null,
      contract: null,
      fidelity: null,
      feeTable: null,
    })
  })

  it("is left out again once the code's own is chosen", () => {
    expect(
      instrumentChosen({ ...UNTOUCHED, instrument: "MES" }, "ES", "ES")
        .instrument
    ).toBeNull()
  })

  it("offers those held with the code's own and the one chosen, by name", () => {
    expect(instrumentChoices(["ES", "MES"], "MES", "MES")).toEqual([
      "ES",
      "MES",
    ])
    expect(instrumentChoices(["BTCUSDT-PERP", "ES"], "MES", "MES")).toEqual([
      "BTCUSDT-PERP",
      "ES",
      "MES",
    ])
    expect(instrumentChoices(["ES"], "ES", "NQ")).toEqual(["ES", "NQ"])
    expect(instrumentChoices([], "MES", "MES")).toEqual(["MES"])
  })
})

describe("estimateAsked of a window that runs backwards", () => {
  it("asks for neither date, which its field refuses", () => {
    expect(
      estimateAsked("v1", {
        ...UNTOUCHED,
        from: "2026-03-09",
        to: "2026-03-06",
      })
    ).toEqual({ strategy_version_id: "v1", settings: {} })
  })
})

describe("readWords", () => {
  it("leaves out the kind of data a run reads none of", () => {
    expect(readWords(ESTIMATE)).toBe("2 sessions, 2,760 bars")
    expect(readWords({ ...ESTIMATE, bars: 0, ticks: 114_749 })).toBe(
      "2 sessions, 114,749 ticks"
    )
    expect(readWords({ ...ESTIMATE, ticks: 12 })).toBe(
      "2 sessions, 2,760 bars, 12 ticks"
    )
    expect(readWords({ ...ESTIMATE, sessions: 0, bars: 0 })).toBe("0 sessions")
  })
})

describe("feeTableOf", () => {
  it("names the table chosen or the default, and none that does not price the root", () => {
    expect(feeTableOf(UNTOUCHED, ESTIMATE)).toBe("retail-default")
    expect(
      feeTableOf({ ...UNTOUCHED, feeTable: "prop-topstep" }, ESTIMATE)
    ).toBe("prop-topstep")
    expect(
      feeTableOf(UNTOUCHED, { ...ESTIMATE, fee_tables: ["prop-topstep"] })
    ).toBeNull()
  })
})

describe("shownDates", () => {
  it("shows what was typed, or the window read, or the data held", () => {
    expect(shownDates(UNTOUCHED, ESTIMATE)).toEqual({
      from: "2026-03-06",
      to: "2026-03-09",
    })
    expect(shownDates({ ...UNTOUCHED, from: "2026-03-07x" }, ESTIMATE)).toEqual(
      { from: "2026-03-07x", to: "2026-03-09" }
    )
    expect(shownDates(UNTOUCHED, { ...ESTIMATE, window: null })).toEqual({
      from: "2026-03-06",
      to: "2026-03-09",
    })
    expect(
      shownDates(UNTOUCHED, { ...ESTIMATE, held: null, window: null })
    ).toBeNull()
  })
})

describe("runReadiness", () => {
  it("sends the window read, the provider applied, and what the trader changed", () => {
    expect(runReadiness("v1", UNTOUCHED, ESTIMATE, true)).toEqual({
      kind: "ready",
      request: {
        strategy_version_id: "v1",
        parameters: {},
        start: "2026-03-06",
        end: "2026-03-09",
        settings: {
          ...THE_RUNS_OWN,
          provider: "synthetic",
          fee_table: "retail-default",
        },
      },
    })
    expect(
      runReadiness(
        "v1",
        {
          ...UNTOUCHED,
          contract: "ESH2026",
          fidelity: "1m",
          feeTable: "prop-topstep",
          slippage: { market: "2", stop: "3" },
          parameters: { lookback: 24 },
        },
        ESTIMATE,
        true
      )
    ).toEqual({
      kind: "ready",
      request: {
        strategy_version_id: "v1",
        parameters: { lookback: 24 },
        start: "2026-03-06",
        end: "2026-03-09",
        settings: {
          ...THE_RUNS_OWN,
          provider: "synthetic",
          contract: "ESH2026",
          fidelity: "1m",
          fee_table: "prop-topstep",
          slippage_ticks: { market: 2, stop: 3 },
        },
      },
    })
  })

  it("sends a side of slippage left alone at the estimate's default", () => {
    const read = runReadiness(
      "v1",
      { ...UNTOUCHED, slippage: { market: "2", stop: null } },
      {
        ...ESTIMATE,
        settings: {
          ...ESTIMATE.settings,
          slippage_ticks: { market: 1, stop: 4 },
        },
      },
      true
    )

    expect(read).toMatchObject({
      kind: "ready",
      request: { settings: { slippage_ticks: { market: 2, stop: 4 } } },
    })
  })

  it("is reading while the estimate is another draft's", () => {
    expect(runReadiness("v1", UNTOUCHED, ESTIMATE, false)).toEqual({
      kind: "reading",
    })
  })

  it.each([
    [
      "a date outside the data",
      { ...UNTOUCHED, from: "2026-03-05" },
      ESTIMATE,
      true,
      "Choose dates the data holds",
    ],
    [
      "dates that meet no data",
      UNTOUCHED,
      { ...ESTIMATE, window: null, sessions: 0 },
      true,
      "Choose dates the data holds",
    ],
    [
      "a window without a session",
      UNTOUCHED,
      { ...ESTIMATE, sessions: 0 },
      true,
      "This window holds no data",
    ],
    [
      "no fee table for the root",
      UNTOUCHED,
      { ...ESTIMATE, fee_tables: [] },
      true,
      "Choose a fee table that prices ES",
    ],
    [
      "ticks that are no number",
      { ...UNTOUCHED, slippage: { market: "1.5", stop: null } },
      ESTIMATE,
      true,
      "Type whole ticks of slippage",
    ],
    [
      "a parameter refused",
      { ...UNTOUCHED, parameters: null },
      ESTIMATE,
      true,
      "Correct the parameter refused above",
    ],
  ])("waits on %s", (_case, draft, estimate, latest, why) => {
    expect(runReadiness("v1", draft, estimate, latest)).toEqual({
      kind: "waiting",
      why,
    })
  })
})
