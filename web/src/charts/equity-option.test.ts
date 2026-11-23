import { describe, expect, it } from "vitest"
import type { ThemeTokens } from "./chart-look"
import { equityOption } from "./equity-option"

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
  const option = equityOption(CURVE, TOKENS)
  const [equity, drawdown] = Array.isArray(option.series) ? option.series : []

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
      const { yAxis } = equityOption({ ...CURVE, equity: [...equity] }, TOKENS)
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
