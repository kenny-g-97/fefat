import { describe, expect, it } from "vitest"
import type { BarColumns } from "@/api/bar-windows"
import { chartPanes } from "./bar-panes"

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
