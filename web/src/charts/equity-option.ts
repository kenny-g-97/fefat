import type { LineSeriesOption } from "echarts/charts"
import type {
  GridComponentOption,
  MarkLineComponentOption,
  TooltipComponentOption,
} from "echarts/components"
import type { ComposeOption } from "echarts/core"
import type { EquityCurve } from "@/api/run-results"
import type { ThemeTokens } from "./chart-look"

/** What `EquityChart` hands ECharts. */
export type EquityOption = ComposeOption<
  | LineSeriesOption
  | GridComponentOption
  | MarkLineComponentOption
  | TooltipComponentOption
>

const FONT = '"Geist Mono", ui-monospace, monospace'
const MILLISECONDS_A_SECOND = 1000
const GRID_SIDES = { left: 72, right: 16 }
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
 * in grey, its axis inverted so that the depth hangs from zero with no figure negated. It runs
 * without animation and without a zoom; each value holds until the next decision, so that a
 * session's break draws flat rather than as a slope; the pointer reads a decision, its crosshair
 * spanning both, and its figures stand in the page's own readout. */
export function equityOption(
  curve: EquityCurve,
  tokens: ThemeTokens
): EquityOption {
  const times = curve.time.map((second) => second * MILLISECONDS_A_SECOND)
  const capitalInView = {
    ...(curve.capital < Math.min(...curve.equity)
      ? { min: curve.capital }
      : {}),
    ...(curve.capital > Math.max(...curve.equity)
      ? { max: curve.capital }
      : {}),
  }
  const labels = {
    color: tokens.mutedForeground,
    fontSize: 12,
    hideOverlap: true,
  }
  const horizontal = {
    show: true,
    lineStyle: { color: tokens.border, width: 1 },
  }
  const noLine = { show: false }
  const timeAxis = {
    type: "time",
    axisLine: noLine,
    axisTick: noLine,
    splitLine: noLine,
  } as const
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: [
      { ...GRID_SIDES, top: 8, height: "60%" },
      { ...GRID_SIDES, top: "70%", bottom: 24 },
    ],
    tooltip: { trigger: "axis", showContent: false },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      snap: true,
      label: { show: false },
      lineStyle: { color: tokens.input, type: "dashed", width: 1 },
    },
    xAxis: [
      { ...timeAxis, gridIndex: 0, axisLabel: { show: false } },
      {
        ...timeAxis,
        gridIndex: 1,
        axisLabel: { ...labels, formatter: TIME_LABELS },
      },
    ],
    yAxis: [
      {
        type: "value",
        gridIndex: 0,
        scale: true,
        ...capitalInView,
        axisLine: noLine,
        axisTick: noLine,
        axisLabel: labels,
        splitLine: horizontal,
      },
      {
        type: "value",
        gridIndex: 1,
        inverse: true,
        min: 0,
        splitNumber: 2,
        axisLine: noLine,
        axisTick: noLine,
        axisLabel: labels,
        splitLine: horizontal,
      },
    ],
    series: [
      {
        type: "line",
        name: "Equity",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: times.map((time, at) => [time, curve.equity[at]]),
        step: "end",
        showSymbol: false,
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
        type: "line",
        name: "Drawdown",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: times.map((time, at) => [time, curve.drawdown[at]]),
        step: "end",
        showSymbol: false,
        lineStyle: { color: tokens.input, width: 1 },
        itemStyle: { color: tokens.input },
        areaStyle: { color: tokens.input, opacity: 0.35 },
      },
    ],
  }
}
