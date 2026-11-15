import { describe, expect, it } from "vitest"
import type { Source } from "@/api/catalog"
import { importedSources } from "./imported-sources"

const GUIDE: readonly Source[] = [
  aSource("databento", "Databento", "vendor", ["databento", "databento-csv"]),
  aSource("kibot", "Kibot", "vendor", []),
  aSource("interactive-brokers", "Interactive Brokers", "vendor", ["ibkr"]),
  aSource("ninjatrader", "NinjaTrader 8", "platform", ["ninjatrader"]),
]

function aSource(
  id: string,
  name: string,
  kind: Source["kind"],
  presets: readonly string[]
): Source {
  return {
    id,
    name,
    kind,
    offers: "",
    cost: "",
    terms: "",
    terms_page: null,
    desktop_use: "check-the-terms",
    desktop_use_note: "",
    licence_scope: "",
    presets: presets.map((preset) => ({
      id: preset,
      name: preset,
      reads: "",
      status: "available",
    })),
  }
}

function aRow(root: string, provider: string) {
  return { root, provider }
}

describe("importedSources", () => {
  it("groups the rows under the source whose presets name their provider, in the list's order", () => {
    // From the builder's fourth check of step 5.4: the sources the trader imported from, each
    // with what was imported from it. Databento reads two layouts, so two providers are its own.
    const rows = [
      aRow("MNQ", "ninjatrader"),
      aRow("MNQ", "databento"),
      aRow("MES", "ibkr"),
      aRow("MES", "databento-csv"),
    ]

    expect(importedSources(rows, GUIDE)).toEqual([
      {
        key: "source ninjatrader",
        name: "NinjaTrader 8",
        note: "Platform",
        rows: [rows[0]],
      },
      {
        key: "source databento",
        name: "Databento",
        note: "Vendor",
        rows: [rows[1], rows[3]],
      },
      {
        key: "source interactive-brokers",
        name: "Interactive Brokers",
        note: "Vendor",
        rows: [rows[2]],
      },
    ])
  })

  it("lists a provider named for a source under that source, and one the guide names nowhere under its own name", () => {
    // A trader's own import profile stores its data under the provider it names: a source's id,
    // such as `kibot`, which has no preset, says which source its files come from, as the
    // dataset's licence scope does (step 5.12, from `BACKLOG.md`); any other name stands apart.
    const rows = [
      aRow("ES", "my-broker"),
      aRow("ES", "kibot"),
      aRow("NQ", "ibkr"),
      aRow("NQ", "interactive-brokers"),
      aRow("CL", "my-broker"),
    ]

    expect(
      importedSources(rows, GUIDE).map((source) => [
        source.key,
        source.name,
        source.note,
        source.rows.map((row) => row.root),
      ])
    ).toEqual([
      [
        "provider my-broker",
        "my-broker",
        "Not in the source guide",
        ["ES", "CL"],
      ],
      ["source kibot", "Kibot", "Vendor", ["ES"]],
      [
        "source interactive-brokers",
        "Interactive Brokers",
        "Vendor",
        ["NQ", "NQ"],
      ],
    ])
  })

  it("lists none where nothing is imported", () => {
    expect(importedSources([], GUIDE)).toEqual([])
  })
})
