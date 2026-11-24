import { describe, expect, it } from "vitest"
import { z } from "zod"
import type { ThemeTokens } from "./chart-look"
import { equityOption } from "./equity-option"

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
  positive: "#10b981",
  negative: "#ff4d6d",
}

const CURVE = {
  capital: 50_000,
  time: [1_772_700_000, 1_772_700_300],
  equity: [49_990.5, 50_012.25],
  drawdown: [9.5, 0],
}

describe("the equity chart's options", () => {
  const option = equityOption(CURVE, "USD", TOKENS)
  const [equity, drawdown] = Array.isArray(option.series) ? option.series : []

  it("keeps one strip for both panes' labels, as wide as a currency's code needs", () => {
    // The reviews of D-117: ECharts shrank a pane alone where its labels overflowed the strip, so
    // the two time axes, and the crosshair across them, fell out of line.
    const sides = (currency: "USD" | "USDT") => {
      const { grid } = equityOption(CURVE, currency, TOKENS)
      return (Array.isArray(grid) ? grid : []).map((pane) => [
        pane.left,
        pane.outerBoundsMode,
      ])
    }

    expect(sides("USD")).toEqual([
      [72, "none"],
      [72, "none"],
    ])
    expect(sides("USDT")).toEqual([
      [95, "none"],
      [95, "none"],
    ])
  })

  it("counts a minus in the strip where the equity falls below zero", () => {
    // The review of the strip: -40,000 USDT is wider than the 90,000 USDT its drawdown reaches.
    const fallen = {
      ...CURVE,
      equity: [50_000, -40_000],
      drawdown: [0, 90_000],
    }
    const { grid } = equityOption(fallen, "USDT", TOKENS)

    expect((Array.isArray(grid) ? grid : []).map((pane) => pane.left)).toEqual([
      102, 102,
    ])
  })

  it("writes both value axes' labels as money in the run's currency", () => {
    // D-117: a cash value reads as one, on the axes too.
    const axes = Array.isArray(option.yAxis) ? option.yAxis : []
    const written = axes.map((axis) =>
      [50_000, -150].map(labelledAxis.parse(axis).axisLabel.formatter)
    )

    expect(written).toEqual([
      ["$50,000", "-$150"],
      ["$50,000", "-$150"],
    ])
  })

  it("draws each decision at its instant, the API's figures unchanged", () => {
    expect(equity.data).toEqual([
      [1_772_700_000_000, 49_990.5],
      [1_772_700_300_000, 50_012.25],
    ])
    expect(drawdown.data).toEqual([
      [1_772_700_000_000, 9.5],
      [1_772_700_300_000, 0],
    ])
  })

  it("leads with the equity in the accent over a line at the capital", () => {
    expect(equity).toMatchObject({
      lineStyle: { color: TOKENS.brand },
      markLine: { data: [{ yAxis: 50_000 }] },
    })
    expect(drawdown).toMatchObject({ lineStyle: { color: TOKENS.input } })
  })

  it("hangs the drawdown from zero on an inverted axis, its figures positive", () => {
    expect(Array.isArray(option.yAxis) && option.yAxis[1]).toMatchObject({
      inverse: true,
      min: 0,
    })
  })

  it("keeps the line at the capital in view, wherever the curve went", () => {
    const axisOf = (equity: readonly number[]) => {
      const { yAxis } = equityOption(
        { ...CURVE, equity: [...equity] },
        "USD",
        TOKENS
      )
      return Array.isArray(yAxis) ? yAxis[0] : yAxis
    }

    expect(axisOf([60_000, 61_000])).toMatchObject({ min: 50_000 })
    expect(axisOf([40_000, 41_000])).toMatchObject({ max: 50_000 })
    expect(axisOf([49_000, 51_000])).not.toHaveProperty("min")
    expect(axisOf([49_000, 51_000])).not.toHaveProperty("max")
  })

  it("holds each value until the next decision, across a session's break", () => {
    expect(equity).toMatchObject({ step: "end" })
    expect(drawdown).toMatchObject({ step: "end" })
  })

  it("starts nothing by itself and offers no zoom", () => {
    expect(option.animation).toBe(false)
    expect(option.tooltip).toMatchObject({ axisPointer: { animation: false } })
    expect(option).not.toHaveProperty("dataZoom")
  })

  it("draws horizontal grid lines alone", () => {
    const axes = Array.isArray(option.xAxis) ? option.xAxis : []
    expect(axes.map((axis) => axis.splitLine?.show)).toEqual([false, false])
    expect(Array.isArray(option.yAxis) && option.yAxis[0]).toMatchObject({
      splitLine: { show: true, lineStyle: { color: TOKENS.border } },
    })
  })
})
