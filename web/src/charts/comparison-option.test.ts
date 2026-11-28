import { describe, expect, it } from "vitest"
import { z } from "zod"
import { contrast, type ThemeTokens } from "./chart-look"
import {
  comparedDays,
  comparisonOption,
  seriesColours,
  shareBounds,
  sharesOn,
} from "./comparison-option"
import { paletteColour } from "./design-palette.test-support"

const SERIES = ["--brand", "--chart-2", "--chart-3", "--chart-4"] as const

function tokensOf(theme: "dark" | "light"): ThemeTokens {
  const colour = (name: string) => paletteColour(name, theme)
  return {
    card: colour("--card"),
    mutedForeground: colour("--muted-foreground"),
    border: colour("--border"),
    input: colour("--input"),
    accent: colour("--accent"),
    brand: colour("--brand"),
    brandSecondary: colour("--brand-secondary"),
    foregroundSecondary: colour("--foreground-secondary"),
    positive: colour("--positive"),
    negative: colour("--negative"),
    chartSecond: colour("--chart-2"),
    chartThird: colour("--chart-3"),
    chartFourth: colour("--chart-4"),
  }
}

const REFERENCE = {
  trade_dates: ["2026-03-05", "2026-03-06", "2026-03-09"],
  shares: [0.99, 0.985, 1.0123],
}
const LATER = {
  trade_dates: ["2026-03-06", "2026-03-09", "2026-03-10"],
  shares: [1.001, 1.004, 1.02],
}

const lineSeries = z.array(
  z.object({
    lineStyle: z.object({
      color: z.string().optional(),
      opacity: z.number().optional(),
    }),
    data: z.array(z.number().nullable()),
    markLine: z
      .object({ data: z.array(z.object({ yAxis: z.number() })) })
      .optional(),
  })
)
const valueAxis = z.object({
  min: z.number(),
  max: z.number(),
  axisLabel: z.object({
    formatter: z.custom<(value: number) => string>(
      (formatter) => typeof formatter === "function"
    ),
  }),
})

describe("the comparison chart's options", () => {
  it("keeps every run's line at 3 : 1 or more on the card in both themes", () => {
    // Step 5.10: the third and fourth series are new tokens of web/DESIGN.md's palette.
    for (const theme of ["dark", "light"] as const) {
      for (const token of SERIES) {
        const ratio = contrast(
          paletteColour(token, theme),
          paletteColour("--card", theme)
        )
        expect(ratio, `${token} in the ${theme} theme`).toBeGreaterThanOrEqual(
          3
        )
      }
    }
  })

  it("draws a line a run, the reference first in the accent, over the capital's dashed line", () => {
    const tokens = tokensOf("dark")

    const [everyDay, ...runs] = lineSeries.parse(
      comparisonOption([REFERENCE, LATER], tokens).series
    )

    expect(runs.map((each) => each.lineStyle.color)).toEqual(
      seriesColours(tokens).slice(0, 2)
    )
    expect(runs[0].markLine?.data).toEqual([{ yAxis: 1 }])
    expect(runs[1].markLine).toBeUndefined()
    // The keys' crosshair shows on the first series, which has a point on every trade date.
    expect(everyDay.data.every((value) => value !== null)).toBe(true)
    expect(everyDay.data).toHaveLength(4)
  })

  it("sets each run's shares on every trade date any run was valued on, none where it was not", () => {
    const days = comparedDays([REFERENCE, LATER])

    expect(days).toEqual([
      "2026-03-05",
      "2026-03-06",
      "2026-03-09",
      "2026-03-10",
    ])
    expect(sharesOn(days, REFERENCE)).toEqual([0.99, 0.985, 1.0123, null])
    expect(sharesOn(days, LATER)).toEqual([null, 1.001, 1.004, 1.02])
  })

  it("keeps the capital in view, its bounds rounded out to a whole percent", () => {
    expect(shareBounds([REFERENCE, LATER])).toEqual({ min: 0.98, max: 1.02 })
    expect(
      shareBounds([{ trade_dates: ["2026-03-05"], shares: [1.2] }])
    ).toEqual({
      min: 1,
      max: 1.2,
    })
  })

  it("writes the value axis in percent of the capital", () => {
    const axis = valueAxis.parse(
      comparisonOption([REFERENCE, LATER], tokensOf("light")).yAxis
    )

    expect([axis.min, axis.max]).toEqual([0.98, 1.02])
    expect(axis.axisLabel.formatter(1.02)).toBe("102%")
    expect(axis.axisLabel.formatter(0.995)).toBe("99.5%")
  })
})
