import { describe, expect, it } from "vitest"
import { executionsFileAddress, tradesFileAddress } from "@/api/trades"
import { columnsKeptIn } from "./kept-columns"
import { tradesSearch } from "./run-search"
import { SHOWN_COLUMNS } from "./trade-columns"

const KEY = "e".repeat(64)

describe("what the trade table asks, kept in its address (step 5.8)", () => {
  it("reads the filters and the order the page wrote, and leaves out what it cannot read", () => {
    const read = tradesSearch.parse({
      key: KEY,
      tab: "sql",
      side: "short",
      exit_reason: "target_1",
      start: "2026-03-05",
      end: "2026-3-9",
      pnl_sign: "losing",
      fidelity: "1m",
      ambiguous: true,
      sort: "side",
      order: "desc",
    })

    expect(read).toEqual({
      key: KEY,
      tab: "sql",
      side: "short",
      exit_reason: "target_1",
      start: "2026-03-05",
      end: undefined,
      pnl_sign: undefined,
      fidelity: "1m",
      ambiguous: true,
      sort: undefined,
      order: "desc",
    })
  })

  it("leaves out a date the calendar does not hold, and both dates where From is after To", () => {
    const impossible = tradesSearch.parse({
      key: KEY,
      start: "2026-02-30",
      end: "2026-03-09",
    })
    const inverted = tradesSearch.parse({
      key: KEY,
      start: "2026-03-09",
      end: "2026-03-05",
    })
    const inOrder = tradesSearch.parse({
      key: KEY,
      start: "2026-03-05",
      end: "2026-03-05",
    })

    expect([impossible.start, impossible.end]).toEqual([
      undefined,
      "2026-03-09",
    ])
    expect([inverted.start, inverted.end]).toEqual([undefined, undefined])
    expect([inOrder.start, inOrder.end]).toEqual(["2026-03-05", "2026-03-05"])
  })
})

describe("the exports' addresses (step 5.8, D-119)", () => {
  it("ask the trades' file for exactly the table's filters and order", () => {
    expect(
      tradesFileAddress(KEY, {
        pnl_sign: "negative",
        exit_reason: "stop",
        side: undefined,
        ambiguous: false,
        sort: "mae_ticks",
        order: "desc",
      })
    ).toBe(
      `/v1/runs/${KEY}/trades.csv?pnl_sign=negative&exit_reason=stop&ambiguous=false&sort=mae_ticks&order=desc`
    )
    expect(tradesFileAddress(KEY, {})).toBe(`/v1/runs/${KEY}/trades.csv`)
    expect(executionsFileAddress(KEY)).toBe(`/v1/runs/${KEY}/executions.csv`)
  })
})

describe("the columns this browser keeps (step 5.8)", () => {
  it("keeps the trader's choice for the columns the table has, its own for the rest", () => {
    const kept = columnsKeptIn(
      JSON.stringify({ fidelity: false, path_fidelity: true, gone: true })
    )

    expect(kept).toEqual({
      ...SHOWN_COLUMNS,
      fidelity: false,
      path_fidelity: true,
    })
  })

  it("takes the table's own columns for nothing kept, or text it cannot read", () => {
    for (const stored of [null, "not json", "[1, 2]", '{"fidelity": "no"}']) {
      expect(columnsKeptIn(stored)).toEqual(SHOWN_COLUMNS)
    }
  })
})
