import { describe, expect, it } from "vitest"
import type { BarColumns } from "@/api/bar-windows"
import type { CatalogStatus, StoredDataset } from "@/api/catalog"
import {
  chartPanes,
  chartRoots,
  contractChoice,
  rootProviders,
} from "./chart-panes"

const BARS: BarColumns = {
  time: [100, 400, 700],
  trade_date: ["2026-03-06", "2026-03-06", "2026-03-09"],
  open: [10, 12, 11],
  high: [12, 13, 12],
  low: [9, 11, 10],
  close: [12, 11, 11],
  volume: [5, 7, 3],
  contract: ["MESH2026", "MESH2026", "MESM2026"],
}

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

describe("chartPanes", () => {
  it("draws the candles over the volume, rising where a close holds its open", () => {
    const [price, volume] = chartPanes(BARS, "5m", true)

    expect([price.id, volume.id]).toEqual(["price", "volume"])
    expect(volume.series[0]).toMatchObject({
      kind: "histogram",
      value: [5, 7, 3],
      rising: [true, false, true],
    })
    expect(price.series[0]).toMatchObject({
      kind: "candles",
      time: [100, 400, 700],
      sessions: BARS.trade_date,
      markers: [{ time: 700, text: "MESM2026" }],
    })
  })

  it("leaves the volume out while hidden, and places daily bars by their trade dates", () => {
    const panes = chartPanes(BARS, "1d", false)

    expect(panes.map((pane) => pane.id)).toEqual(["price"])
    expect(panes[0].series[0]).toMatchObject({ time: BARS.trade_date })
    expect(panes[0].series[0]).not.toHaveProperty("sessions")
  })
})

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
