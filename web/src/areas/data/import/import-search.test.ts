import { describe, expect, it } from "vitest"
import { LISTED } from "./import-fixtures.test-support"
import { backOf, importSearch, presetChoice } from "./import-search"

describe("presetChoice", () => {
  it("chooses Databento's batches, a profile by its name, or the one saved for a provider", () => {
    expect(presetChoice("databento", LISTED)).toEqual({ kind: "batch" })
    expect(presetChoice("ninjatrader", LISTED)).toEqual({
      kind: "profile",
      name: "ninjatrader",
    })
    expect(presetChoice("kibot", LISTED)).toEqual({
      kind: "profile",
      name: "my-ninjatrader",
    })
  })

  it("chooses nothing for no preset, or a provider without exactly one saved profile", () => {
    expect(presetChoice(undefined, LISTED)).toEqual({ kind: "none" })
    expect(presetChoice("synthetic", LISTED)).toEqual({ kind: "none" })
    const twice = [
      ...LISTED,
      ...LISTED.filter((each) => each.origin === "saved"),
    ]
    expect(presetChoice("kibot", twice)).toEqual({ kind: "none" })
  })
})

describe("importSearch", () => {
  it("reads the step shown from the address, and any value it cannot read as none (D-105)", () => {
    for (const step of ["file", "layout", "instrument", "review"]) {
      expect(importSearch.parse({ step }).step).toBe(step)
    }
    expect(importSearch.parse({ step: "summary" }).step).toBeUndefined()
    expect(importSearch.parse({ step: 2 }).step).toBeUndefined()
    expect(importSearch.parse({ preset: "ninjatrader" }).step).toBeUndefined()
  })
})

describe("backOf", () => {
  it("leads back to where the page was opened from, the Data page by default", () => {
    expect(backOf(importSearch.parse({}))).toEqual({ kind: "data" })
    expect(backOf(importSearch.parse({ from: "sources" }))).toEqual({
      kind: "sources",
    })
    expect(
      backOf(
        importSearch.parse({
          from: "dataset",
          instrument: "MES",
          provider: "databento",
        })
      )
    ).toEqual({ kind: "dataset", instrument: "MES", provider: "databento" })
  })

  it("reads a page it does not know, or a dataset without its names, as the Data page", () => {
    expect(backOf(importSearch.parse({ from: "elsewhere" }))).toEqual({
      kind: "data",
    })
    expect(backOf(importSearch.parse({ from: "dataset" }))).toEqual({
      kind: "data",
    })
  })
})
