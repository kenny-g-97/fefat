import { describe, expect, it } from "vitest"
import type { DeletionPreview, StoredDataset } from "@/api/catalog"
import type { ImportedDataset } from "./datasets"
import { deletionWords } from "./deletion-words"

const MINUTES: StoredDataset = {
  id: "ninjatrader:ohlcv-1m:ES",
  provider: "ninjatrader",
  root: "ES",
  schema_name: "ohlcv-1m",
  fidelity: "1m",
  contracts: 30,
  first_trade_date: "2019-03-01",
  last_trade_date: "2026-06-19",
  quality: "clean",
  checked_through: "2026-06-19",
  origin: "import",
  licence_scope: "Your own export",
  last_import: "2026-11-18",
}

const ES: ImportedDataset = {
  root: "ES",
  provider: "ninjatrader",
  type: "market",
  stored: [MINUTES],
  kinds: ["1-minute bars"],
  from: "2019-03-01",
  to: "2026-06-19",
  quality: "clean",
  product: null,
}

function aPreview(changes: Partial<DeletionPreview>): DeletionPreview {
  return {
    provider: "ninjatrader",
    root: "ES",
    imported_files: 0,
    kept_files: [],
    quality_report: false,
    saved_runs: 0,
    ...changes,
  }
}

describe("deletionWords", () => {
  it("says what goes, what stays, the saved runs, and that a delete cannot be undone", () => {
    expect(
      deletionWords(
        ES,
        aPreview({ imported_files: 27, quality_report: true, saved_runs: 3 })
      )
    ).toEqual([
      "1-minute bars from 2019-03-01 to 2026-06-19 are deleted, with FEAT's copies of the 27 files they were imported from and the quality report.",
      "Your own files stay where you keep them, and can be imported again afterwards.",
      "3 saved runs read this data: they keep their results, but FEAT can no longer explain their trades or check them again.",
      "This cannot be undone.",
    ])
  })

  it("names every kind of data, and one file and one run in the singular", () => {
    const held = { ...ES, kinds: ["Trades", "1-second bars", "1-minute bars"] }

    expect(
      deletionWords(held, aPreview({ imported_files: 1, saved_runs: 1 }))
    ).toEqual([
      "Trades, 1-second bars, and 1-minute bars from 2019-03-01 to 2026-06-19 are deleted, with FEAT's copy of the file they were imported from.",
      "Your own files stay where you keep them, and can be imported again afterwards.",
      "1 saved run read this data: it keeps its results, but FEAT can no longer explain its trades or check it again.",
      "This cannot be undone.",
    ])
  })

  it("names a kind inside the sentence in lower case, but an acronym as it is", () => {
    const held = { ...ES, kinds: ["1-minute bars", "TBBO", "Trades"] }

    expect(deletionWords(held, aPreview({}))[0]).toBe(
      "1-minute bars, TBBO, and trades from 2019-03-01 to 2026-06-19 are deleted."
    )
  })

  it("says the data alone where FEAT holds no copy and no report, and no saved run", () => {
    expect(deletionWords(ES, aPreview({}))).toEqual([
      "1-minute bars from 2019-03-01 to 2026-06-19 are deleted.",
      "Your own files stay where you keep them, and can be imported again afterwards.",
      "No saved run read this data.",
      "This cannot be undone.",
    ])
  })

  it("names a file FEAT keeps since it also holds another instrument, and counts several", () => {
    const one = deletionWords(
      ES,
      aPreview({ kept_files: ["glbx-mdp3-20260304.ohlcv-1m.dbn.zst"] })
    )
    const several = deletionWords(
      ES,
      aPreview({ kept_files: ["a.dbn", "b.dbn", "c.dbn"] })
    )

    expect(one[2]).toBe(
      "FEAT keeps its copy of glbx-mdp3-20260304.ohlcv-1m.dbn.zst, which also holds another instrument still stored: importing it again adds nothing until that one is deleted too."
    )
    expect(several[2]).toBe(
      "FEAT keeps its copies of 3 files that also hold another instrument still stored: importing them again adds nothing until those are deleted too."
    )
  })
})
