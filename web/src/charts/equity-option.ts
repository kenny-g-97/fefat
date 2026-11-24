import type { LineSeriesOption } from "echarts/charts"
import type { EquityCurve } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import type { ThemeTokens } from "./chart-look"
import {
  axisLabels,
  capitalInView,
  capitalLine,
  FONT,
  GRID_RIGHT,
  labelStrip,
  moneyAxis,
  NO_LINE,
  pointerOptions,
  type ResultsChartOption,
} from "./results-chart"

const MILLISECONDS_A_SECOND = 1000
/** The time axis's labels, in the app's one date format, in this browser's time zone. */
const TIME_LABELS = {
  year: "{yyyy}",
  month: "{yyyy}-{MM}",
  day: "{MM}-{dd}",
  hour: "{HH}:{mm}",
  minute: "{HH}:{mm}",
  second: "{HH}:{mm}:{ss}",
  millisecond: "{HH}:{mm}:{ss}",
  none: "{yyyy}-{MM}-{dd} {HH}:{mm}",
}

/** The chart of `curve` in the theme's `tokens` (web/DESIGN.md, Patterns, Charts): the equity in
 * the accent over a dashed line at the capital, and under it, on the same time axis, its drawdown
 * in grey, its axis inverted so that the depth hangs from zero with no figure negated, both axes
 * written as money in `currency`. Nothing animates, the axis pointer included, and there is no
 * zoom; each value holds until the next decision, so that a session's break draws flat rather
 * than as a slope; the pointer reads a decision, its crosshair spanning both, and its figures
 * stand in the page's own readout. */
export function equityOption(
  curve: EquityCurve,
  currency: Currency,
  tokens: ThemeTokens
): ResultsChartOption {
  const sides = {
    left: labelStrip(
      [curve.capital, ...curve.equity, ...curve.drawdown],
      currency
    ),
    right: GRID_RIGHT,
    outerBoundsMode: "none",
  } as const
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: [
      { ...sides, top: 8, height: "60%" },
      { ...sides, top: "70%", bottom: 24 },
    ],
    ...pointerOptions(tokens),
    ...equityAxes(curve, currency, tokens),
    series: equitySeries(curve, tokens),
  }
}

/** One time axis over two value axes in `currency`, with horizontal grid lines alone, the upper
 * keeping the capital in view wherever the curve went. */
function equityAxes(
  curve: EquityCurve,
  currency: Currency,
  tokens: ThemeTokens
): Pick<ResultsChartOption, "xAxis" | "yAxis"> {
  const value = moneyAxis(tokens, currency)
  const time = {
    type: "time",
    axisLine: NO_LINE,
    axisTick: NO_LINE,
    splitLine: NO_LINE,
  } as const
  return {
    xAxis: [
      { ...time, gridIndex: 0, axisLabel: { show: false } },
      {
        ...time,
        gridIndex: 1,
        axisLabel: { ...axisLabels(tokens), formatter: TIME_LABELS },
      },
    ],
    yAxis: [
      {
        ...value,
        gridIndex: 0,
        scale: true,
        ...capitalInView(
          curve.capital,
          Math.min(...curve.equity),
          Math.max(...curve.equity)
        ),
      },
      { ...value, gridIndex: 1, inverse: true, min: 0, splitNumber: 2 },
    ],
  }
}

/** The equity with its line at the capital, and the drawdown as an area, each decision at its
 * instant, the API's figures unchanged. */
function equitySeries(
  curve: EquityCurve,
  tokens: ThemeTokens
): LineSeriesOption[] {
  const times = curve.time.map((second) => second * MILLISECONDS_A_SECOND)
  const line = {
    type: "line",
    step: "end",
    symbol: "circle",
    showSymbol: false,
  } as const
  return [
    {
      ...line,
      name: "Equity",
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: times.map((time, at) => [time, curve.equity[at]]),
      lineStyle: { color: tokens.brand, width: 1.5 },
      itemStyle: { color: tokens.brand },
      markLine: capitalLine(curve.capital, tokens),
    },
    {
      ...line,
      name: "Drawdown",
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: times.map((time, at) => [time, curve.drawdown[at]]),
      lineStyle: { color: tokens.input, width: 1 },
      itemStyle: { color: tokens.input },
      areaStyle: { color: tokens.input, opacity: 0.35 },
    },
  ]
}
