import { describe, expect, it } from "vitest"
import type { StoredDataset, SyncCover } from "@/api/catalog"
import { importedDatasets } from "./datasets"
import {
  drawnRow,
  filterChoices,
  type ImportedFilters,
  KNOWN_VALUES,
  type ListedRow,
  matching,
  NO_FILTERS,
} from "./imported-filters"

const MNQ: ListedRow = {
  instrument: "MNQ",
  provider: "databento",
  type: "Market",
  kinds: ["Trades", "1-minute bars"],
  from: "2019-05-06",
  to: "2026-10-30",
  quality: "Clean",
}
const MNQ_FILE: ListedRow = {
  ...MNQ,
  provider: "databento-csv",
  kinds: ["1-minute bars"],
  quality: "Flagged",
}
const MES: ListedRow = {
  instrument: "MES",
  provider: "ninjatrader",
  type: "Market",
  kinds: ["1-minute bars"],
  from: "2025-04-01",
  to: "2026-03-31",
  quality: "Unchecked",
}
const ES: ListedRow = {
  instrument: "ES",
  provider: "databento",
  type: "Market",
  kinds: ["1-second bars"],
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
    expect(found("minute bars")).toEqual([MNQ, MNQ_FILE, MES])
    expect(found("2025")).toEqual([MES])
    expect(found("checking")).toEqual([ES])
    expect(found("clean mnq")).toEqual([MNQ])
    expect(found("mnq ninjatrader")).toEqual([])
    // A word is found in one cell, never across two: no cell of ES's row reads "esdatabento",
    // and no kind of MNQ's data reads "tradesbars".
    expect(found("esdatabento")).toEqual([])
    expect(found("trades1-minute")).toEqual([])
    // A comma parts words as a space does, so the Data cell typed as it reads is found (step
    // 5.4's reviews of the fourth check's fixes): "trades," is no kind's word, "trades" is.
    expect(found("Trades, 1-minute bars")).toEqual([MNQ])
    expect(found("1-minute bars,trades")).toEqual([MNQ])
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
      { ...MNQ, standing: "clean" },
      { ...MES, standing: "unchecked" },
    ]

    expect(
      matching(drawn, asked({ instrument: "MES" })).map((row) => row.standing)
    ).toEqual(["unchecked"])
  })
})

describe("filterChoices", () => {
  it("offers each column's values once, in the list's order", () => {
    expect(filterChoices(ROWS, NO_FILTERS, {})).toEqual({
      instrument: ["MNQ", "MES", "ES"],
      provider: ["databento", "databento-csv", "ninjatrader"],
      type: ["Market"],
      quality: ["Clean", "Flagged", "Unchecked", "Checking"],
    })
    expect(filterChoices([], NO_FILTERS, {}).provider).toEqual([])
  })

  it("offers a column of few known values in that column's own order, whatever the rows'", () => {
    // Step 5.4's design review of the fourth check: Quality's choices changed places from one
    // store to the next, and after a check.
    const order = ["Flagged", "Stale", "Unchecked", "Checking", "Clean"]

    expect(filterChoices(ROWS, NO_FILTERS, { quality: order }).quality).toEqual(
      ["Flagged", "Unchecked", "Checking", "Clean"]
    )
    expect(
      filterChoices(ROWS, NO_FILTERS, { quality: order }).instrument
    ).toEqual(["MNQ", "MES", "ES"])
    // A value the order does not name is offered still, after those it names.
    expect(
      filterChoices(ROWS, NO_FILTERS, { quality: ["Flagged", "Clean"] }).quality
    ).toEqual(["Flagged", "Clean", "Unchecked", "Checking"])
  })

  it("orders the list's type and quality as the design system has them", () => {
    // The Quality dropdown's order is `STANDING_LABELS`' own, which a reordered key would move.
    expect(KNOWN_VALUES).toEqual({
      type: ["Market"],
      quality: ["Flagged", "Stale", "Unchecked", "Checking", "Clean"],
    })
  })

  it("keeps a chosen value the rows no longer show, so that its dropdown still names it", () => {
    // A check that ends while Quality asks for Checking leaves no row that reads so.
    const chosen = asked({ quality: "Stale", instrument: "NQ" })
    const order = ["Flagged", "Stale", "Unchecked", "Checking", "Clean"]

    // A chosen value the rows still show is offered once, in its place.
    expect(
      filterChoices(ROWS, asked({ instrument: "MES" }), {}).instrument
    ).toEqual(["MNQ", "MES", "ES"])

    expect(filterChoices(ROWS, chosen, {}).quality).toEqual([
      "Clean",
      "Flagged",
      "Unchecked",
      "Checking",
      "Stale",
    ])
    expect(filterChoices(ROWS, chosen, {}).instrument).toEqual([
      "MNQ",
      "MES",
      "ES",
      "NQ",
    ])
    // In its place among a known column's values.
    expect(filterChoices(ROWS, chosen, { quality: order }).quality).toEqual(
      order
    )
  })
})

describe("drawnRow", () => {
  it("gives a dataset's row the words its cells show, which its filters read too", () => {
    // Step 5.4's code review of the fourth check: the list drew a row from its dataset and
    // filtered it by words built apart, two copies that could drift.
    const stored = (fidelity: string): StoredDataset => ({
      id: `ibkr:${fidelity}:MNQ`,
      provider: "ibkr",
      root: "MNQ",
      schema_name: fidelity,
      fidelity,
      contracts: 1,
      first_trade_date: "2026-09-21",
      last_trade_date: "2026-09-23",
      quality: "clean",
      checked_through: null,
      origin: "import",
      licence_scope: "Personal",
      last_import: null,
    })
    const [dataset] = importedDatasets({
      version: 1,
      products: [],
      unlisted: [stored("trades"), stored("1m")],
    })
    const none: SyncCover = { every: false, roots: new Set() }
    const ofMnq: SyncCover = { every: false, roots: new Set(["MNQ"]) }

    expect(drawnRow(dataset, none)).toEqual({
      instrument: "MNQ",
      provider: "ibkr",
      type: "Market",
      kinds: ["Trades", "1-minute bars"],
      from: "2026-09-21",
      to: "2026-09-23",
      quality: "Clean",
      standing: "clean",
    })
    expect(drawnRow(dataset, ofMnq)).toMatchObject({
      quality: "Checking",
      standing: "checking",
    })
  })
})
