import { describe, expect, it } from "vitest"
import {
  filterChoices,
  type ImportedFilters,
  type ListedRow,
  matching,
  NO_FILTERS,
} from "./imported-filters"

const MNQ: ListedRow = {
  instrument: "MNQ",
  provider: "databento",
  type: "Market",
  data: "Trades, 1-minute bars",
  from: "2019-05-06",
  to: "2026-10-30",
  quality: "Clean",
}
const MNQ_FILE: ListedRow = {
  ...MNQ,
  provider: "databento-csv",
  data: "1-minute bars",
  quality: "Flagged",
}
const MES: ListedRow = {
  instrument: "MES",
  provider: "ninjatrader",
  type: "Market",
  data: "1-minute bars",
  from: "2025-04-01",
  to: "2026-03-31",
  quality: "Unchecked",
}
const ES: ListedRow = {
  instrument: "ES",
  provider: "databento",
  type: "Market",
  data: "1-second bars",
  from: "2026-03-05",
  to: "2026-03-09",
  quality: "Checking",
}
const ROWS = [MNQ, MNQ_FILE, MES, ES]

function asked(change: Partial<ImportedFilters>): ImportedFilters {
  return { ...NO_FILTERS, ...change }
}

describe("matching", () => {
  it("keeps every row while nothing is asked", () => {
    expect(matching(ROWS, NO_FILTERS)).toEqual(ROWS)
    expect(matching(ROWS, asked({ search: "   " }))).toEqual(ROWS)
  })

  it("keeps the rows that hold every word typed, each in some cell, capitals ignored", () => {
    // From the builder's fourth check of step 5.4: a search through the imported data.
    const found = (search: string) => matching(ROWS, asked({ search }))

    expect(found("mnq")).toEqual([MNQ, MNQ_FILE])
    expect(found("DataBento  mnq")).toEqual([MNQ, MNQ_FILE])
    expect(found("trades")).toEqual([MNQ])
    expect(found("2025")).toEqual([MES])
    expect(found("checking")).toEqual([ES])
    expect(found("clean mnq")).toEqual([MNQ])
    expect(found("mnq ninjatrader")).toEqual([])
    // A word is found in one cell, never across two: no cell of ES's row reads "esdatabento".
    expect(found("esdatabento")).toEqual([])
  })

  it("keeps the rows that show a dropdown's value, the value whole", () => {
    // ES is another instrument than MES, and databento another provider than databento-csv.
    expect(matching(ROWS, asked({ instrument: "ES" }))).toEqual([ES])
    expect(matching(ROWS, asked({ provider: "databento" }))).toEqual([MNQ, ES])
    expect(matching(ROWS, asked({ quality: "Checking" }))).toEqual([ES])
    expect(matching(ROWS, asked({ type: "Market" }))).toEqual(ROWS)
    expect(matching(ROWS, asked({ type: "Alternative" }))).toEqual([])
  })

  it("asks the search and every dropdown at once", () => {
    const both = { search: "bars", instrument: "MNQ" }

    expect(matching(ROWS, asked({ ...both, provider: "databento" }))).toEqual([
      MNQ,
    ])
    expect(matching(ROWS, asked({ ...both, quality: "Unchecked" }))).toEqual([])
  })

  it("gives back the rows it was given, with what the list draws of them", () => {
    const drawn = [
      { ...MNQ, dataset: "the first" },
      { ...MES, dataset: "the second" },
    ]

    expect(
      matching(drawn, asked({ instrument: "MES" })).map((row) => row.dataset)
    ).toEqual(["the second"])
  })
})

describe("filterChoices", () => {
  it("offers each column's values once, in the list's order", () => {
    expect(filterChoices(ROWS, NO_FILTERS)).toEqual({
      instrument: ["MNQ", "MES", "ES"],
      provider: ["databento", "databento-csv", "ninjatrader"],
      type: ["Market"],
      quality: ["Clean", "Flagged", "Unchecked", "Checking"],
    })
    expect(filterChoices([], NO_FILTERS).provider).toEqual([])
  })

  it("keeps a chosen value the rows no longer show, so that its dropdown still names it", () => {
    // A check that ends while Quality asks for Checking leaves no row that reads so.
    const chosen = asked({ quality: "Stale", instrument: "MES" })

    expect(filterChoices(ROWS, chosen).quality).toEqual([
      "Clean",
      "Flagged",
      "Unchecked",
      "Checking",
      "Stale",
    ])
    expect(filterChoices(ROWS, chosen).instrument).toEqual(["MNQ", "MES", "ES"])
  })
})
