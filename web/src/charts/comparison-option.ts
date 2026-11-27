import type { LineSeriesOption } from "echarts/charts"
import type { ShareCurve } from "@/api/comparisons"
import { shareEdge } from "@/ui/figures"
import type { ThemeTokens } from "./chart-look"
import {
  axisLabels,
  capitalLine,
  FONT,
  GRID_RIGHT,
  NO_LINE,
  pointerOptions,
  type ResultsChartOption,
} from "./results-chart"

/** The strip left of the pane for its labels: `-100%` to `1,000%` at 12 px of Geist Mono. */
const LABEL_STRIP = 64

/** The colour of each run's curve, in the comparison's order: the reference in the accent, the
 * others in the series tokens (web/DESIGN.md, Palette, Charts). */
export function seriesColours(tokens: ThemeTokens): readonly string[] {
  return [
    tokens.brand,
    tokens.chartSecond,
    tokens.chartThird,
    tokens.chartFourth,
  ]
}

/** Every trade date any of `curves` was valued on, in order: the chart's one axis, on which a
 * run without a value on a date has none there. */
export function comparedDays(curves: readonly ShareCurve[]): readonly string[] {
  const days = new Set(curves.flatMap((curve) => curve.trade_dates))
  return [...days].sort()
}

/** Each curve's share on each of `days`, null where it was not valued that day. */
export function sharesOn(
  days: readonly string[],
  curve: ShareCurve
): readonly (number | null)[] {
  const byDay = new Map(
    curve.trade_dates.map((day, at) => [day, curve.shares[at]])
  )
  return days.map((day) => {
    const share = byDay.get(day)
    return share === undefined ? null : share
  })
}

/** The value axis's bounds, every share and the capital's 1 in view, rounded outward to a whole
 * percent, since ECharts labels a bound it is given with the decimals it holds. */
export function shareBounds(
  curves: readonly ShareCurve[]
): Readonly<{ min: number; max: number }> {
  const shares = [1, ...curves.flatMap((curve) => curve.shares)]
  return {
    min: Math.floor(Math.min(...shares) * 100) / 100,
    max: Math.ceil(Math.max(...shares) * 100) / 100,
  }
}

/** Two to four runs' equity over their capital on one axis of trade dates (web/DESIGN.md,
 * Patterns, Comparison chart): a line each in its series colour, the reference's first, over a
 * dashed line at the capital, with horizontal grid lines in the hairline alone and the value axis
 * in percent of the capital; no animation and no tooltip, the page's readout holding the figures. */
export function comparisonOption(
  curves: readonly ShareCurve[],
  tokens: ThemeTokens
): ResultsChartOption {
  const days = comparedDays(curves)
  const colours = seriesColours(tokens)
  const series: LineSeriesOption[] = curves.map((curve, at) => ({
    type: "line",
    name: `Run ${at + 1}`,
    symbol: "circle",
    showSymbol: false,
    connectNulls: false,
    data: [...sharesOn(days, curve)],
    lineStyle: { color: colours[at], width: 1.5 },
    itemStyle: { color: colours[at] },
    emphasis: { disabled: true },
    ...(at === 0 ? { markLine: capitalLine(1, tokens) } : {}),
  }))
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: { left: LABEL_STRIP, right: GRID_RIGHT, top: 8, bottom: 28 },
    ...pointerOptions(tokens),
    xAxis: {
      type: "category",
      data: [...days],
      boundaryGap: false,
      axisLine: NO_LINE,
      axisTick: NO_LINE,
      axisLabel: axisLabels(tokens),
    },
    yAxis: {
      type: "value",
      ...shareBounds(curves),
      axisLine: NO_LINE,
      axisTick: NO_LINE,
      axisLabel: { ...axisLabels(tokens), formatter: shareEdge },
      splitLine: { show: true, lineStyle: { color: tokens.border, width: 1 } },
    },
    series,
  }
}
