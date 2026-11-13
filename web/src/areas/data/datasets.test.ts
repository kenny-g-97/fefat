import { describe, expect, it } from "vitest"
import type { CatalogStatus, MonthCoverage, StoredDataset } from "@/api/catalog"
import {
  byProvider,
  byRoot,
  catalogLine,
  chartTimeframe,
  fidelityLabel,
  importedDatasets,
  monthHeld,
  monthLabel,
  notImported,
} from "./datasets"

type CatalogProduct = CatalogStatus["products"][number]

describe("importedDatasets", () => {
  it("gives a row for each instrument and provider that holds data, in the API's order", () => {
    // From the builder's second check of step 5.4: the Data page lists what was imported, a
    // row an instrument's data from one provider, a catalog product's or not.
    const mnq: CatalogProduct = {
      root: "MNQ",
      history_from: "2019-05-06",
      recommended_source: "Databento",
      // The earliest and the latest trade date are neither the first dataset's.
      datasets: [
        {
          ...aDataset("databento", "MNQ", "1s"),
          first_trade_date: "2026-09-21",
          last_trade_date: "2026-09-23",
          coverage: "partial",
        },
        {
          ...aDataset("databento", "MNQ", "1m"),
          first_trade_date: "2019-05-06",
          last_trade_date: "2026-09-22",
          coverage: "complete",
        },
        {
          ...aDataset("databento", "MNQ", "trades"),
          first_trade_date: "2026-09-22",
          last_trade_date: "2026-09-24",
          coverage: "partial",
        },
        { ...aDataset("ninjatrader", "MNQ", "1m"), coverage: "partial" },
      ],
    }
    const mcl: CatalogProduct = {
      root: "MCL",
      history_from: "2021-07-12",
      recommended_source: "Databento",
      datasets: [],
    }
    const catalog: CatalogStatus = {
      version: 1,
      products: [mnq, mcl],
      unlisted: [
        aDataset("synthetic", "ES", "1s"),
        aDataset("synthetic", "BTCUSDT-PERP", "1m"),
      ],
    }

    const rows = importedDatasets(catalog)

    expect(
      rows.map((row) => [row.root, row.provider, row.kinds, row.from, row.to])
    ).toEqual([
      [
        "MNQ",
        "databento",
        "1-second bars, 1-minute bars, Trades",
        "2019-05-06",
        "2026-09-24",
      ],
      ["MNQ", "ninjatrader", "1-minute bars", "2026-03-05", "2026-03-09"],
      ["ES", "synthetic", "1-second bars", "2026-03-05", "2026-03-09"],
      [
        "BTCUSDT-PERP",
        "synthetic",
        "1-minute bars",
        "2026-03-05",
        "2026-03-09",
      ],
    ])
    expect(rows.map((row) => row.stored.length)).toEqual([3, 1, 1, 1])
    expect(rows.map((row) => row.product)).toEqual([mnq, mnq, null, null])
    expect(notImported(catalog)).toEqual([mcl])
    expect(catalogLine(mcl)).toBe(
      "History from 2021-07-12, Databento recommended"
    )
  })

  it("reads a row's quality as stale once one of its datasets outgrew the report", () => {
    // A clean report is stale for the dataset an import grew since (`quality_verdict`), so a
    // provider's datasets of a root can read clean and stale side by side.
    const minutes: StoredDataset = {
      ...aDataset("databento", "MNQ", "1m"),
      quality: "clean",
    }
    const trades: StoredDataset = {
      ...aDataset("databento", "MNQ", "trades"),
      quality: "stale",
    }
    const flagged: StoredDataset = {
      ...aDataset("ninjatrader", "MNQ", "1m"),
      quality: "flagged",
    }
    const catalog: CatalogStatus = {
      version: 1,
      products: [],
      unlisted: [minutes, trades, flagged],
    }

    expect(importedDatasets(catalog).map((row) => row.quality)).toEqual([
      "stale",
      "flagged",
    ])
    expect(
      importedDatasets({ ...catalog, unlisted: [minutes] }).map(
        (row) => row.quality
      )
    ).toEqual(["clean"])
  })
})

describe("chartTimeframe", () => {
  it("opens at five minutes, or at the first timeframe a provider's longer bars build", () => {
    // Step 5.4's code review: a provider of hourly bars alone opened its chart at five minutes,
    // which the SDK refuses.
    const of = (...fidelities: string[]) =>
      chartTimeframe(fidelities.map((each) => aDataset("p", "ES", each)))

    expect([of("1m", "trades"), of("tbbo"), of("1s"), of("5m")]).toEqual([
      "5m",
      "5m",
      "5m",
      "5m",
    ])
    expect([of("1h"), of("2h"), of("1d"), of("1d", "30m")]).toEqual([
      "1h",
      "4h",
      "1d",
      "30m",
    ])
  })
})

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
