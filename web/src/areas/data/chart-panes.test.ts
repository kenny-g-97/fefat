import { describe, expect, it } from "vitest"
import type { CatalogStatus, StoredDataset } from "@/api/catalog"
import { chartRoots, contractChoice, rootProviders } from "./chart-panes"

function aDataset(provider: string, root: string): StoredDataset {
  return {
    id: `${provider}:ohlcv-1m:${root}`,
    provider,
    root,
    schema_name: "ohlcv-1m",
    fidelity: "1m",
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

describe("the choices", () => {
  it("offer the products holding data first, then the trader's own roots, each provider once", () => {
    const catalog: CatalogStatus = {
      version: 1,
      products: [
        {
          root: "MES",
          history_from: "2019-05-06",
          recommended_source: "Databento",
          datasets: [{ ...aDataset("databento", "MES"), coverage: "complete" }],
        },
        {
          root: "MCL",
          history_from: "2021-07-12",
          recommended_source: "Databento",
          datasets: [],
        },
      ],
      unlisted: [aDataset("synthetic", "ES"), aDataset("ninjatrader", "ES")],
    }

    expect(chartRoots(catalog)).toEqual(["MES", "ES"])
    expect(rootProviders(catalog, "ES")).toEqual(["synthetic", "ninjatrader"])
  })

  it("chart a contract of the root alone, the root for nothing, and refuse another", () => {
    expect(contractChoice("MES", " mesm2026 ", 2026)).toEqual({
      kind: "contract",
      contract: "MESM2026",
    })
    expect(contractChoice("MES", "", 2026)).toEqual({ kind: "root" })
    expect(contractChoice("MES", "MNQZ2025", 2026)).toEqual({
      kind: "refused",
      message: "Type a contract of MES, such as MESM2026.",
    })
  })
})
