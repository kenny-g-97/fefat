import { describe, expect, it } from "vitest"
import { z } from "zod"
import { contrast, type ThemeTokens } from "./chart-look"
import { painted, paletteColour } from "./design-palette.test-support"
import { fanOption, INNER_BAND, OUTER_BAND } from "./fan-option"

/** A series' points, each a count of trades and an amount. */
const points = z.array(z.tuple([z.number(), z.number()]))

/** A line series' colour, as the option holds it. */
const lineColour = z.object({ lineStyle: z.object({ color: z.string() }) })

/** The colour of the dashed line a series carries, as the median carries the capital's. */
const markColour = z.object({
  markLine: z.object({ lineStyle: z.object({ color: z.string() }) }),
})

/** An axis whose labels a function writes, as ECharts calls it with each tick's value. */
const labelledAxis = z.object({
  axisLabel: z.object({
    formatter: z.custom<(value: number) => string>(
      (formatter) => typeof formatter === "function"
    ),
  }),
})

const TOKENS: ThemeTokens = {
  card: "#0a0a0a",
  mutedForeground: "#7c7c7c",
  border: "#1a1a1a",
  input: "#666666",
  accent: "#1a1a1a",
  brand: "#fc734d",
  brandSecondary: "#a855f7",
  foregroundSecondary: "#888888",
  positive: "#10b981",
  negative: "#ff4d6d",
  chartSecond: "#06b6d4",
}

const FAN = {
  capital: 50_000,
  trades_made: [0, 1, 2],
  p5: [50_000, 49_900.5, 49_800.1],
  p25: [50_000, 49_950.25, 49_900.7],
  median: [50_000, 50_010, 50_020.25],
  p75: [50_000, 50_060.3, 50_120.9],
  p95: [50_000, 50_110.6, 50_230.75],
  own: [50_000, 50_070.5, 49_960.25],
}

describe("the Monte Carlo fan's options", () => {
  const option = fanOption(FAN, "USD", TOKENS)
  const series = Array.isArray(option.series) ? option.series : []
  const layers = series.slice(0, 4)
  const median = series[4]
  const own = series[5]

  it("stacks its bands so that each layer's top stands at one of the API's percentiles", () => {
    // Step 5.20: the 5th, 25th, 75th, and 95th percentiles bound the two bands.
    const heights = layers.map((layer) => points.parse(layer.data))
    const tops = heights.map((_, upTo) =>
      FAN.trades_made.map((_, at) =>
        heights.slice(0, upTo + 1).reduce((top, layer) => top + layer[at][1], 0)
      )
    )
    const percentiles = [FAN.p5, FAN.p25, FAN.p75, FAN.p95]

    tops.forEach((top, layer) =>
      top.forEach((amount, at) =>
        expect(amount).toBeCloseTo(percentiles[layer][at], 6)
      )
    )
    expect(heights.map((layer) => layer.map(([made]) => made))).toEqual([
      FAN.trades_made,
      FAN.trades_made,
      FAN.trades_made,
      FAN.trades_made,
    ])
    expect(layers.map((layer) => [layer.stack, layer.stackStrategy])).toEqual(
      Array(4).fill(["fan", "all"])
    )
  })

  it("fills the middle half darker than the rest of the middle nine in ten, in grey", () => {
    expect(layers[0]).not.toHaveProperty("areaStyle")
    expect(layers.slice(1).map((layer) => layer.areaStyle)).toEqual([
      { color: TOKENS.input, opacity: OUTER_BAND },
      { color: TOKENS.input, opacity: INNER_BAND },
      { color: TOKENS.input, opacity: OUTER_BAND },
    ])
    expect(layers.map((layer) => layer.lineStyle)).toEqual(
      Array(4).fill({ opacity: 0 })
    )
  })

  it("leads with the median in the accent over a line at the capital, the API's figures unchanged", () => {
    expect(points.parse(median.data)).toEqual([
      [0, 50_000],
      [1, 50_010],
      [2, 50_020.25],
    ])
    expect(median).toMatchObject({
      lineStyle: { color: TOKENS.brand },
      markLine: {
        data: [{ yAxis: 50_000 }],
        lineStyle: { color: TOKENS.foregroundSecondary, type: "dashed" },
      },
    })
  })

  it("draws the run's own walk over the bands in the purple, the API's figures unchanged", () => {
    // Step 5.21: the run's own path over its paths, the builder's exception to the cyan (D-119).
    expect(points.parse(own.data)).toEqual([
      [0, 50_000],
      [1, 50_070.5],
      [2, 49_960.25],
    ])
    expect(own).toMatchObject({
      name: "This run",
      lineStyle: { color: TOKENS.brandSecondary, width: 1.5 },
    })
    expect(series).toHaveLength(6)
  })

  it("writes its amounts as money and its counts of trades as whole numbers", () => {
    // D-117: a cash value reads as one, on the axis too.
    expect(
      [50_000, -150].map(labelledAxis.parse(option.yAxis).axisLabel.formatter)
    ).toEqual(["$50,000", "-$150"])
    expect(
      [0, 1234].map(labelledAxis.parse(option.xAxis).axisLabel.formatter)
    ).toEqual(["0", "1,234"])
    expect(option.xAxis).toMatchObject({
      type: "value",
      min: 0,
      max: "dataMax",
      minInterval: 1,
    })
  })

  it("keeps its strip as wide as a currency's code needs", () => {
    const left = (currency: "USD" | "USDT") => {
      const { grid } = fanOption(FAN, currency, TOKENS)
      return Array.isArray(grid) ? null : grid?.left
    }

    expect(left("USD")).toBe(72)
    expect(left("USDT")).toBe(95)
  })

  it.each(["dark", "light"] as const)(
    "keeps every line it draws at 3 : 1 against either band in the %s theme",
    (theme) => {
      // The design reviews: WCAG 1.4.11, a line keeps 3 : 1 against any band it crosses
      // (web/DESIGN.md, Charts); at 60 % the middle band left the median 2.95 : 1 in the light
      // theme, at 55 % the run's own purple 2.75 : 1 in the dark one, and the dashed capital in the
      // field border's grey stood at 2.19 : 1 on the middle band (step 5.21).
      const token = (name: string) => paletteColour(name, theme)
      const themed: ThemeTokens = {
        ...TOKENS,
        card: token("--card"),
        input: token("--input"),
        brand: token("--brand"),
        brandSecondary: token("--brand-secondary"),
        foregroundSecondary: token("--foreground-secondary"),
      }
      const drawn = fanOption(FAN, "USD", themed).series
      const [median, own] = (Array.isArray(drawn) ? drawn : []).slice(4)
      const capital = markColour.parse(median).markLine.lineStyle.color
      const colours = [median, own].map(
        (line) => lineColour.parse(line).lineStyle.color
      )

      const ratios = [...colours, capital].flatMap((colour) =>
        [OUTER_BAND, INNER_BAND].map((fill) =>
          contrast(colour, painted(themed.input, themed.card, fill))
        )
      )

      expect(ratios).toHaveLength(6)
      ratios.forEach((ratio) => expect(ratio).toBeGreaterThanOrEqual(3))
    }
  )

  it("starts nothing by itself, offers no zoom, and draws horizontal grid lines alone", () => {
    expect(option.animation).toBe(false)
    expect(option.tooltip).toMatchObject({ axisPointer: { animation: false } })
    expect(option).not.toHaveProperty("dataZoom")
    expect(option.xAxis).toMatchObject({ splitLine: { show: false } })
    expect(option.yAxis).toMatchObject({
      splitLine: { show: true, lineStyle: { color: TOKENS.border } },
    })
  })
})
