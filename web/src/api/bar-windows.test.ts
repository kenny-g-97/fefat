import { describe, expect, it } from "vitest"
import {
  type BarColumns,
  barWindows,
  BUCKETS_PER_WINDOW,
  DAYS_PER_WINDOW,
  joinedBars,
  timeframe,
  timeframeSeconds,
  windowDays,
} from "./bar-windows"

const MES_YEAR = { first: "2025-04-01", last: "2026-03-31" }

function bars(...times: number[]): BarColumns {
  return {
    time: times,
    trade_date: times.map(() => "2026-03-06"),
    open: times.map((each) => each + 0.25),
    high: times.map((each) => each + 0.5),
    low: times.map((each) => each),
    close: times.map((each) => each + 0.25),
    volume: times.map(() => 10),
    contract: times.map(() => "MESM2026"),
  }
}

describe("windowDays", () => {
  it("spans at most 20,000 bars and a year in every timeframe the chart offers", () => {
    // Done means 2: no request larger than 20,000 bars, a window holding at most
    // BUCKETS_PER_WINDOW, were every hour of every day traded.
    for (const each of timeframe.options) {
      const days = windowDays(each)
      const buckets = (days * 86_400) / timeframeSeconds(each)
      expect(buckets, each).toBeLessThanOrEqual(BUCKETS_PER_WINDOW)
      expect(buckets, each).toBeLessThan(20_000)
      expect(days, each).toBeLessThanOrEqual(DAYS_PER_WINDOW)
    }
    expect(timeframe.options.map(windowDays)).toEqual([
      5, 27, 83, 166, 333, 366, 366,
    ])
  })
})

describe("barWindows", () => {
  it("walks back from the last trade date held to the first, newest first", () => {
    const windows = barWindows(MES_YEAR, "5m")

    expect(windows.at(0)?.to).toBe("2026-03-31")
    expect(windows.at(-1)?.from).toBe("2025-04-01")
    expect(windows.length).toBe(14)
    windows.slice(1).forEach((older, index) => {
      const newer = windows[index]
      expect(
        older.to < (newer?.from ?? ""),
        `${older.to} before ${newer?.from}`
      ).toBe(true)
    })
  })

  it("keeps a window's dates when the data grows, but the newest's end", () => {
    const now = barWindows(MES_YEAR, "5m")
    const later = barWindows({ ...MES_YEAR, last: "2026-04-03" }, "5m")

    expect(later.slice(1)).toEqual(now.slice(1))
    expect(later.at(0)).toEqual({ from: now.at(0)?.from, to: "2026-04-03" })
  })

  it("refuses a date the API does not write and dates out of order", () => {
    expect(() =>
      barWindows({ first: "2026-3-6", last: "2026-03-09" }, "5m")
    ).toThrow('Expected a trade date such as 2026-03-06, got "2026-3-6".')
    expect(() =>
      barWindows({ first: "2026-03-09", last: "2026-03-06" }, "5m")
    ).toThrow("Expected held dates in order, got 2026-03-09 to 2026-03-06.")
  })
})

describe("joinedBars", () => {
  it("joins the windows loaded in a row from the newest, oldest first", () => {
    const joined = joinedBars([
      bars(500, 600),
      bars(300, 400),
      undefined,
      bars(100),
    ])

    expect(joined.time).toEqual([300, 400, 500, 600])
    expect(joined.close).toEqual([300.25, 400.25, 500.25, 600.25])
  })

  it("refuses windows whose bars overlap", () => {
    expect(() => joinedBars([bars(400, 500), bars(300, 400)])).toThrow(
      "Expected each window's bars before the next window's, got 400 at or after 400."
    )
  })

  it("joins an empty window as nothing", () => {
    expect(joinedBars([bars(), bars(100)]).time).toEqual([100])
  })
})
