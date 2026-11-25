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
/** The fill between the equity and its capital, a share of the line's sign colour. */
export const EQUITY_FILL = 0.3
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

/** The chart of `curve` in the theme's `tokens` (web/DESIGN.md, Patterns, Equity chart): the
 * equity over a dashed line at the capital, in the sign colours, green where the account stands
 * above its capital and red below, filled to the capital (D-119), and under it, on the same time
 * axis, its drawdown in grey, its axis inverted so that the depth hangs from zero with no figure
 * negated, both axes written as money in `currency`. Nothing animates, the axis pointer included,
 * and there is no zoom; each value holds until the next decision, so that a session's break draws
 * flat rather than as a slope; the pointer reads a decision, its crosshair spanning both, and its
 * figures stand in the page's own readout. */
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
    visualMap: signColours(curve, tokens),
    series: equitySeries(curve, tokens),
  }
}

/** The equity's colours by its value: the negative under the capital and the positive from it
 * up. ECharts draws a line's colours by value from the pieces closed at both ends, a piece open at
 * one giving the colours beyond them, and reads which way the axis runs from a closed piece's two
 * ends, so the positive takes one from the capital to a unit of money above it, since a piece of
 * no height turns the colours upside down, and another above that. A run that never leaves its
 * capital, as one that never traded, takes the capital line's grey, since a line lying on the
 * capital splits along its width where the colours meet. */
function signColours(
  curve: EquityCurve,
  tokens: ThemeTokens
): ResultsChartOption["visualMap"] {
  const unitAbove = curve.capital + 1
  const [below, above] = curve.equity.every((value) => value === curve.capital)
    ? [tokens.input, tokens.input]
    : [tokens.negative, tokens.positive]
  return {
    type: "piecewise",
    show: false,
    seriesIndex: 0,
    dimension: 1,
    pieces: [
      { lt: curve.capital, color: below },
      { gte: curve.capital, lte: unitAbove, color: above },
      { gt: unitAbove, color: above },
    ],
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

/** The equity with its line at the capital, coloured by the visual map, which a colour of its own
 * would override, and filled to the capital; and the drawdown as an area, each decision at its
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
      lineStyle: { width: 1.5 },
      areaStyle: { origin: curve.capital, opacity: EQUITY_FILL },
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
