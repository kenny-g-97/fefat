import { describe, expect, it } from "vitest"
import type { RunEstimated } from "@/api/runs"
import {
  estimateAsked,
  estimateWords,
  feeTableOf,
  instrumentChoices,
  instrumentChosen,
  isTradeDate,
  readWords,
  runReadiness,
  shownDates,
  stressedSearch,
  ticksRefusal,
  tradeDateRefusal,
  UNTOUCHED,
  windowRefusal,
} from "./run-draft"

const HELD = { start: "2026-03-06", end: "2026-03-09" }

const PROP_TOPSTEP = {
  name: "prop-topstep",
  fee: { kind: "futures", per_contract_side: "1.89" },
} as const

const ESTIMATE: RunEstimated = {
  state: "estimated",
  instrument: "ES",
  timeframe: "5m",
  instruments: ["ES", "MES"],
  providers: ["synthetic"],
  contracts: ["ESH2026", "ESM2026"],
  levels: ["1m"],
  fee_tables: [
    {
      name: "retail-default",
      fee: { kind: "futures", per_contract_side: "2.87" },
    },
    PROP_TOPSTEP,
  ],
  currency: "USD",
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
  it("is asked of the estimate once chosen, and every run names the one read", () => {
    const moved = { ...UNTOUCHED, instrument: "MES" }

    expect(estimateAsked("v1", moved).settings).toEqual({ instrument: "MES" })
    const ready = runReadiness(
      "v1",
      moved,
      { ...ESTIMATE, instrument: "MES" },
      true
    )
    const own = runReadiness("v1", UNTOUCHED, ESTIMATE, true)
    expect(ready.kind === "ready" && ready.request.settings?.instrument).toBe(
      "MES"
    )
    // Named at the code's own too, so that a parameter of the code cannot trade another.
    expect(own.kind === "ready" && own.request.settings?.instrument).toBe("ES")
  })

  it("says what the run trades beside what it reads, where the code names another", () => {
    expect(estimateWords(ESTIMATE, "ES")).toBe("2 sessions, 2,760 bars")
    expect(estimateWords({ ...ESTIMATE, instrument: "MNQ" }, "ES")).toBe(
      "Trades MNQ, not the code's ES: 2 sessions, 2,760 bars"
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

describe("stressedSearch", () => {
  const of = (name: string) => ({ strategy: { name } })

  it("filters the list by the strategy while every run stands under it", () => {
    expect(stressedSearch([of("demo"), of("demo")], "demo")).toEqual({
      strategy: "demo",
    })
  })

  it("leaves the filter out where a run found saved stands elsewhere", () => {
    expect(stressedSearch([of("demo"), of("other")], "demo")).toEqual({})
    expect(stressedSearch([of("demo"), { strategy: null }], "demo")).toEqual({})
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
      feeTableOf(UNTOUCHED, { ...ESTIMATE, fee_tables: [PROP_TOPSTEP] })
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
          instrument: "ES",
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
          instrument: "ES",
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
      "No commissions and fees for ES",
    ],
    [
      "a fee table chosen that the estimate no longer offers",
      { ...UNTOUCHED, feeTable: "prop-topstep" },
      { ...ESTIMATE, fee_tables: [ESTIMATE.fee_tables[0]] },
      true,
      "Choose commissions and fees for ES",
    ],
    [
      "a fidelity left from another instrument's data",
      { ...UNTOUCHED, fidelity: "tbbo" },
      ESTIMATE,
      true,
      "Choose a fidelity the data holds",
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
