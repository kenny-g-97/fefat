import type { LineSeriesOption } from "echarts/charts"
import type { EquityFan } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { formatCount } from "@/ui/figures"
import type { ThemeTokens } from "./chart-look"
import {
  axisLabels,
  capitalLine,
  FONT,
  GRID_RIGHT,
  labelStrip,
  moneyAxis,
  NO_LINE,
  pointerOptions,
  type ResultsChartOption,
} from "./results-chart"

/** The fill of the paths between their 5th and 25th, and 75th and 95th percentiles. */
export const OUTER_BAND = 0.3
/** The fill of the paths between their 25th and 75th percentiles. */
export const INNER_BAND = 0.55

/** The chart of `fan` in the theme's `tokens` (web/DESIGN.md, Patterns, Fan chart), in the equity
 * chart's idiom: the paths' median equity in the accent over a dashed line at the capital, and
 * behind it the middle half of the paths and the middle nine in ten as two greys, by the count of
 * trades made, the value axis written as money in `currency`, the capital in view since every
 * percentile starts there. Nothing animates and there is no zoom; the pointer reads a count, and
 * its figures stand in the page's own readout. */
export function fanOption(
  fan: EquityFan,
  currency: Currency,
  tokens: ThemeTokens
): ResultsChartOption {
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: {
      left: labelStrip([fan.capital, ...fan.p5, ...fan.p95], currency),
      right: GRID_RIGHT,
      top: 8,
      bottom: 24,
      outerBoundsMode: "none",
    },
    ...pointerOptions(tokens),
    xAxis: {
      type: "value",
      min: 0,
      max: "dataMax",
      minInterval: 1,
      axisLine: NO_LINE,
      axisTick: NO_LINE,
      splitLine: NO_LINE,
      axisLabel: {
        ...axisLabels(tokens),
        formatter: (count: number) => formatCount(count),
      },
    },
    yAxis: { ...moneyAxis(tokens, currency), scale: true },
    series: fanSeries(fan, tokens),
  }
}

/** The bands as layers of one stack over an unfilled base at the 5th percentile, each as tall as
 * the gap between two of the API's percentiles, so that its top stands at the higher, and the
 * median over them. */
function fanSeries(fan: EquityFan, tokens: ThemeTokens): LineSeriesOption[] {
  const stacked = (
    name: string,
    heights: readonly number[]
  ): LineSeriesOption => ({
    type: "line",
    name,
    stack: "fan",
    stackStrategy: "all",
    symbol: "none",
    silent: true,
    data: fan.trades_made.map((made, at) => [made, heights[at]]),
    lineStyle: { opacity: 0 },
  })
  const band = (
    name: string,
    low: readonly number[],
    high: readonly number[],
    fill: number
  ): LineSeriesOption => ({
    ...stacked(
      name,
      high.map((amount, at) => amount - low[at])
    ),
    areaStyle: { color: tokens.input, opacity: fill },
  })
  return [
    stacked("5th percentile", fan.p5),
    band("5th to 25th percentile", fan.p5, fan.p25, OUTER_BAND),
    band("25th to 75th percentile", fan.p25, fan.p75, INNER_BAND),
    band("75th to 95th percentile", fan.p75, fan.p95, OUTER_BAND),
    {
      type: "line",
      name: "Median",
      symbol: "circle",
      showSymbol: false,
      data: fan.trades_made.map((made, at) => [made, fan.median[at]]),
      lineStyle: { color: tokens.brand, width: 1.5 },
      itemStyle: { color: tokens.brand },
      markLine: capitalLine(fan.capital, tokens),
    },
  ]
}
