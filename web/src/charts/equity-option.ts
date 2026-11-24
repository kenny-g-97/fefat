import type { LineSeriesOption } from "echarts/charts"
import type {
  GridComponentOption,
  MarkLineComponentOption,
  TooltipComponentOption,
} from "echarts/components"
import type { ComposeOption } from "echarts/core"
import type { EquityCurve } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { moneyEdge } from "@/ui/figures"
import type { ThemeTokens } from "./chart-look"

/** What `EquityChart` hands ECharts. */
type EquityOption = ComposeOption<
  | LineSeriesOption
  | GridComponentOption
  | MarkLineComponentOption
  | TooltipComponentOption
>

const FONT = '"Geist Mono", ui-monospace, monospace'
const MILLISECONDS_A_SECOND = 1000
const GRID_RIGHT = 16
/** The strip left of both panes for their value axes' labels, at its narrowest. */
const LABEL_STRIP = 72
/** A character of the axes' labels at 12 px of Geist Mono, 0.6 of an em wide. */
const LABEL_CHARACTER = 7.2
/** ECharts' room between a value axis's label and its pane. */
const LABEL_MARGIN = 8
const NO_LINE = { show: false }
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
): EquityOption {
  const sides = {
    left: labelStrip(curve, currency),
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
    tooltip: {
      trigger: "axis",
      showContent: false,
      axisPointer: { animation: false },
    },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      snap: true,
      label: { show: false },
      lineStyle: { color: tokens.input, type: "dashed", width: 1 },
    },
    ...equityAxes(curve, currency, tokens),
    series: equitySeries(curve, tokens),
  }
}

/** The strip left of both panes for their value axes' labels, one width so that the two time axes
 * line up, ECharts moving neither pane for its labels: room for the widest amount either axis can
 * label in `currency`, a digit more for a tick rounded past it (D-117). */
function labelStrip(curve: EquityCurve, currency: Currency): number {
  const widest = [curve.capital, ...curve.equity, ...curve.drawdown].reduce(
    (wide, amount) => Math.max(wide, Math.abs(amount)),
    0
  )
  const characters = moneyEdge(Math.round(widest), currency).length + 1
  return Math.max(
    LABEL_STRIP,
    Math.ceil(characters * LABEL_CHARACTER) + LABEL_MARGIN
  )
}

/** One time axis over two value axes in `currency`, with horizontal grid lines alone, the upper
 * keeping the capital in view wherever the curve went. */
function equityAxes(
  curve: EquityCurve,
  currency: Currency,
  tokens: ThemeTokens
): Pick<EquityOption, "xAxis" | "yAxis"> {
  const labels = {
    color: tokens.mutedForeground,
    fontSize: 12,
    hideOverlap: true,
  }
  const value = {
    type: "value",
    axisLine: NO_LINE,
    axisTick: NO_LINE,
    axisLabel: {
      ...labels,
      formatter: (amount: number) => moneyEdge(amount, currency),
    },
    splitLine: { show: true, lineStyle: { color: tokens.border, width: 1 } },
  } as const
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
        axisLabel: { ...labels, formatter: TIME_LABELS },
      },
    ],
    yAxis: [
      {
        ...value,
        gridIndex: 0,
        scale: true,
        ...(curve.capital < Math.min(...curve.equity)
          ? { min: curve.capital }
          : {}),
        ...(curve.capital > Math.max(...curve.equity)
          ? { max: curve.capital }
          : {}),
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
      markLine: {
        silent: true,
        symbol: "none",
        label: { show: false },
        lineStyle: { color: tokens.input, type: "dashed", width: 1 },
        data: [{ yAxis: curve.capital }],
      },
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
