import { describe, expect, it } from "vitest"
import { z } from "zod"
import { contrast, type ThemeTokens } from "./chart-look"
import { paletteColour } from "./design-palette.test-support"
import { percentileOption } from "./percentile-option"

/** A series' points, each a percent of the paths and the figure there, none where a path has none. */
const points = z.array(z.tuple([z.number(), z.number().nullable()]))

/** An axis whose labels a function writes, as ECharts calls it with each tick's value. */
const labelledAxis = z.object({
  axisLabel: z.object({
    formatter: z.custom<(value: number) => string>(
      (formatter) => typeof formatter === "function"
    ),
  }),
})

/** A line series with the mark line of the run's own figure, as the option holds it. */
const markedSeries = z.object({
  lineStyle: z.object({ color: z.string() }),
  markLine: z.object({
    lineStyle: z.object({ color: z.string(), type: z.literal("dashed") }),
    data: z.tuple([z.object({ yAxis: z.number() })]),
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
}

const PERCENTS = Array.from({ length: 101 }, (_, percent) => percent)
const DRAWDOWN = {
  at_percent: PERCENTS.map((percent) => 400 + percent * 37.5),
  own: 1730.25,
}
const FACTORS = {
  at_percent: PERCENTS.map((percent) =>
    percent > 96 ? null : 0.5 + percent / 40
  ),
  own: null,
}

/** The chart's series of `figure`: the unseen base at every percent, then the paths' line. */
function seriesOf(figure: typeof DRAWDOWN | typeof FACTORS) {
  const { series } = percentileOption(figure, null, TOKENS)
  return Array.isArray(series) ? series : []
}

describe("a Monte Carlo figure's chart against the percent of its paths", () => {
  it("draws the API's figure at each percent in the accent, a gap where a path has none", () => {
    const [, drawdown] = seriesOf(DRAWDOWN)
    const [, factors] = seriesOf(FACTORS)

    expect(points.parse(drawdown.data)).toEqual(
      PERCENTS.map((percent) => [percent, DRAWDOWN.at_percent[percent]])
    )
    expect(points.parse(factors.data).slice(95)).toEqual([
      [95, 0.5 + 95 / 40],
      [96, 0.5 + 96 / 40],
      [97, null],
      [98, null],
      [99, null],
      [100, null],
    ])
    expect(drawdown).toMatchObject({ lineStyle: { color: TOKENS.brand } })
  })

  it("marks the run's own figure as a dashed line in the purple, and none where it has none", () => {
    // D-119: the run's own stands in the purple, the builder's exception to the cyan.
    const [, drawdown] = seriesOf(DRAWDOWN)

    const marked = markedSeries.parse(drawdown)

    expect(marked.markLine.data).toEqual([{ yAxis: 1730.25 }])
    expect(marked.markLine.lineStyle.color).toBe(TOKENS.brandSecondary)
    expect(seriesOf(FACTORS)[1]).not.toHaveProperty("markLine")
  })

  it("holds an unseen point at every percent, where the keys' crosshair stands over a gap", () => {
    // The lean review: the keys show the tip on the first series, and ECharts hides its
    // crosshair at a point without a value, as a path without a profit factor has.
    const [base] = seriesOf(FACTORS)

    expect(points.parse(base.data)).toEqual(
      PERCENTS.map((percent) => [percent, 0.5])
    )
    expect(base).toMatchObject({
      silent: true,
      symbol: "none",
      lineStyle: { opacity: 0 },
    })
    expect(base).not.toHaveProperty("areaStyle")
  })

  it("keeps the run's own figure in view where it stands past every path, at a whole number", () => {
    // The lean review: ECharts labels the bound it is given, and the strip holds whole numbers,
    // so 1,334.56 USDT at the axis's end lost its first digit.
    const above = { ...DRAWDOWN, own: 5000.25 }
    const below = { ...DRAWDOWN, own: 100.75 }
    const whole = { ...DRAWDOWN, own: 5000 }

    expect(percentileOption(above, null, TOKENS).yAxis).toMatchObject({
      max: 5001,
    })
    expect(percentileOption(below, null, TOKENS).yAxis).toMatchObject({
      min: 100,
    })
    expect(percentileOption(whole, null, TOKENS).yAxis).toMatchObject({
      max: 5000,
    })
    const within = percentileOption(DRAWDOWN, null, TOKENS).yAxis
    expect(within).not.toHaveProperty("max")
    expect(within).not.toHaveProperty("min")
  })

  it("writes its percents, and its figures as money in a currency or plain without one", () => {
    // D-117: money reads as money on the axis too; ticks and ratios as the histograms' edges.
    const money = percentileOption(DRAWDOWN, "USD", TOKENS)
    const plain = percentileOption(FACTORS, null, TOKENS)

    expect(
      [0, 50, 100].map(labelledAxis.parse(money.xAxis).axisLabel.formatter)
    ).toEqual(["0%", "50%", "100%"])
    expect(
      [1500, -150].map(labelledAxis.parse(money.yAxis).axisLabel.formatter)
    ).toEqual(["$1,500", "-$150"])
    expect(
      [1.25, 1234].map(labelledAxis.parse(plain.yAxis).axisLabel.formatter)
    ).toEqual(["1.25", "1,234"])
    expect(money.xAxis).toMatchObject({
      type: "value",
      min: 0,
      max: 100,
      interval: 10,
    })
  })

  it("starts nothing by itself, offers no zoom, and draws horizontal grid lines alone", () => {
    const option = percentileOption(DRAWDOWN, "USD", TOKENS)

    expect(option.animation).toBe(false)
    expect(option.tooltip).toMatchObject({ axisPointer: { animation: false } })
    expect(option).not.toHaveProperty("dataZoom")
    expect(option.xAxis).toMatchObject({ splitLine: { show: false } })
    expect(option.yAxis).toMatchObject({
      splitLine: { show: true, lineStyle: { color: TOKENS.border } },
    })
  })

  it("refuses a figure no path has, whose chart says why in its place", () => {
    const none = { at_percent: PERCENTS.map(() => null), own: null }

    expect(() => percentileOption(none, null, TOKENS)).toThrow(
      /Expected a figure of at least one path/
    )
  })

  it.each(["dark", "light"] as const)(
    "keeps the paths' line and the run's own at 3 : 1 against the card in the %s theme",
    (theme) => {
      // WCAG 1.4.11: a line keeps 3 : 1 against what it crosses, here the card alone.
      const token = (name: string) => paletteColour(name, theme)

      const ratios = ["--brand", "--brand-secondary"].map((line) =>
        contrast(token(line), token("--card"))
      )

      ratios.forEach((ratio) => expect(ratio).toBeGreaterThanOrEqual(3))
    }
  )
})
