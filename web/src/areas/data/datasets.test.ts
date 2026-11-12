import { describe, expect, it } from "vitest"
import type { MonthCoverage, StoredDataset } from "@/api/catalog"
import {
  byProvider,
  byRoot,
  fidelityLabel,
  monthHeld,
  monthLabel,
} from "./datasets"

function aDataset(
  provider: string,
  root: string,
  fidelity: string
): StoredDataset {
  return {
    id: `${provider}:ohlcv-${fidelity}:${root}`,
    provider,
    root,
    schema_name: `ohlcv-${fidelity}`,
    fidelity,
    contracts: 1,
    first_trade_date: "2026-03-05",
    last_trade_date: "2026-03-09",
    quality: "unchecked",
    checked_through: null,
    origin: "import",
    licence_scope: "Synthetic",
    last_import: null,
  }
}

function aMonth(changes: Partial<MonthCoverage>): MonthCoverage {
  return {
    month: "2026-03",
    sessions: 22,
    with_records: 22,
    tick_days: 0,
    second_days: 0,
    minute_days: 22,
    findings: 0,
    vendor_flagged: 0,
    ...changes,
  }
}

describe("the groups", () => {
  it("keep the API's order, each provider and each root once", () => {
    const datasets = [
      aDataset("databento", "MNQ", "1m"),
      aDataset("ninjatrader", "MNQ", "1m"),
      aDataset("databento", "MES", "1m"),
    ]

    expect(
      byProvider(datasets).map((each) => [each.name, each.datasets.length])
    ).toEqual([
      ["databento", 2],
      ["ninjatrader", 1],
    ])
    expect(byRoot(datasets).map((each) => each.name)).toEqual(["MNQ", "MES"])
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

describe("the months", () => {
  it("are held by every session, some, or none, and say so in words", () => {
    const some = aMonth({ with_records: 20, findings: 1, vendor_flagged: 2 })

    expect(
      [aMonth({}), some, aMonth({ with_records: 0 })].map(monthHeld)
    ).toEqual(["every", "some", "none"])
    expect(monthLabel(aMonth({}))).toBe(
      "2026-03: 22 of 22 sessions with records, no findings"
    )
    expect(monthLabel(some)).toBe(
      "2026-03: 20 of 22 sessions with records, 1 finding, 2 sessions the vendor flagged"
    )
  })
})
