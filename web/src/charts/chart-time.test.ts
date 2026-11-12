import { describe, expect, it } from "vitest"
import { barTime, chartTime, crosshairTime, tickMarkLabel } from "./chart-time"

// 15:00 UTC on 2026-03-06 is 09:00 in Chicago (CST); 14:30 UTC on 2026-03-09, after the change
// to daylight saving on 03-08, is 09:30 (CDT). The tests run in America/Chicago (vite.config.ts).
const FRIDAY_AT_NINE = Date.UTC(2026, 2, 6, 15) / 1000
const MONDAY_AT_HALF_PAST_NINE = Date.UTC(2026, 2, 9, 14, 30) / 1000

describe("chartTime", () => {
  it("takes an open in whole seconds or a trade date, and refuses a fraction of a second", () => {
    expect(chartTime(FRIDAY_AT_NINE)).toBe(FRIDAY_AT_NINE)
    expect(chartTime("2026-03-06")).toBe("2026-03-06")
    expect(() => chartTime(FRIDAY_AT_NINE + 0.5)).toThrow(
      `Expected a bar's open in whole seconds, got ${FRIDAY_AT_NINE + 0.5}.`
    )
  })

  it("gives a trade date the chart gives back as fields as its text", () => {
    expect(barTime({ year: 2026, month: 3, day: 6 })).toBe("2026-03-06")
    expect(barTime("2026-03-06")).toBe("2026-03-06")
  })
})

describe("the labels", () => {
  it("show an open in the browser's zone, across a change to daylight saving", () => {
    expect(crosshairTime(FRIDAY_AT_NINE)).toBe("2026-03-06 09:00")
    expect(crosshairTime(MONDAY_AT_HALF_PAST_NINE)).toBe("2026-03-09 09:30")
    expect(crosshairTime("2026-03-06")).toBe("2026-03-06")
  })

  it("mark times of day in the browser's zone and days by the UTC date they fall on", () => {
    const evening = Date.UTC(2026, 2, 6, 0) / 1000

    expect(tickMarkLabel(FRIDAY_AT_NINE, "time")).toBe("09:00")
    expect(tickMarkLabel(FRIDAY_AT_NINE + 5, "seconds")).toBe("09:00:05")
    expect(tickMarkLabel(evening, "day")).toBe("03-06")
    expect(tickMarkLabel(evening, "month")).toBe("2026-03")
    expect(tickMarkLabel(evening, "year")).toBe("2026")
    expect(tickMarkLabel("2026-03-06", "day")).toBe("03-06")
  })
})
