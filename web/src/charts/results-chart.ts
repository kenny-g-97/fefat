import type { LineSeriesOption } from "echarts/charts"
import type {
  GridComponentOption,
  MarkLineComponentOption,
  TooltipComponentOption,
  VisualMapComponentOption,
} from "echarts/components"
import type { ComposeOption } from "echarts/core"
import type { Currency } from "@/api/runs"
import { moneyEdge } from "@/ui/figures"
import type { ThemeTokens } from "./chart-look"

/** What a results chart hands ECharts: lines over grids, a mark line, the axis pointer, and a
 * visual map colouring a line by its value, the parts `PointedChart` registers. */
export type ResultsChartOption = ComposeOption<
  | LineSeriesOption
  | GridComponentOption
  | MarkLineComponentOption
  | TooltipComponentOption
  | VisualMapComponentOption
>

export const FONT = '"Geist Mono", ui-monospace, monospace'
export const GRID_RIGHT = 16
export const NO_LINE = { show: false }
/** The strip left of a pane for its value axis's labels, at its narrowest. */
const LABEL_STRIP = 72
/** A character of the axes' labels at 12 px of Geist Mono, 0.6 of an em wide. */
const LABEL_CHARACTER = 7.2
/** ECharts' room between a value axis's label and its pane. */
const LABEL_MARGIN = 8

/** The strip left of a chart's panes for their value axes' labels, one width so that panes over
 * one time axis line up, ECharts moving no pane for its labels: room for the wider of the lowest
 * and the highest of `amounts` in `currency`, or plain where none, a minus counted, and a digit
 * more for a tick rounded past it (D-117). */
export function labelStrip(
  amounts: readonly number[],
  currency: Currency | null
): number {
  const written = [Math.min(...amounts), Math.max(...amounts)].map(
    (amount) => moneyEdge(Math.round(amount), currency).length
  )
  const characters = Math.max(...written) + 1
  return Math.max(
    LABEL_STRIP,
    Math.ceil(characters * LABEL_CHARACTER) + LABEL_MARGIN
  )
}

/** An axis's labels: 12 px in subtle text, none drawn over another. */
export function axisLabels(tokens: ThemeTokens) {
  return { color: tokens.mutedForeground, fontSize: 12, hideOverlap: true }
}

/** A value axis of money in `currency`, or of plain figures where none, as ticks and ratios, the
 * histograms' edges, with horizontal grid lines in the hairline alone. */
export function valueAxis(tokens: ThemeTokens, currency: Currency | null) {
  return {
    type: "value",
    axisLine: NO_LINE,
    axisTick: NO_LINE,
    axisLabel: {
      ...axisLabels(tokens),
      formatter: (amount: number) => moneyEdge(amount, currency),
    },
    splitLine: { show: true, lineStyle: { color: tokens.border, width: 1 } },
  } as const
}

/** The bounds that keep `level`, such as the capital or the run's own figure, in view of an axis
 * whose values run from `lowest` to `highest`. */
export function keptInView(
  level: number,
  lowest: number,
  highest: number
): Readonly<{ min?: number; max?: number }> {
  return {
    ...(level < lowest ? { min: level } : {}),
    ...(level > highest ? { max: level } : {}),
  }
}

/** The axis pointer a readout follows: a dashed crosshair snapping to an entry, across every
 * pane, with no tooltip of its own and no animation, since the page's readout holds the figures. */
export function pointerOptions(
  tokens: ThemeTokens
): Pick<ResultsChartOption, "tooltip" | "axisPointer"> {
  return {
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
  }
}

/** A dashed line at `capital` in the field border's grey, which nothing points at. */
export function capitalLine(
  capital: number,
  tokens: ThemeTokens
): LineSeriesOption["markLine"] {
  return dashedAt(capital, tokens.input, 1)
}

/** A dashed line at the run's `own` figure in the purple, the builder's exception to the cyan
 * for the run among its Monte Carlo's paths (D-119), which nothing points at. */
export function ownLine(
  own: number,
  tokens: ThemeTokens
): LineSeriesOption["markLine"] {
  return dashedAt(own, tokens.brandSecondary, 1.5)
}

/** A dashed line at `level` in `colour`, `width` px wide, which nothing points at. */
function dashedAt(
  level: number,
  colour: string,
  width: number
): LineSeriesOption["markLine"] {
  return {
    silent: true,
    symbol: "none",
    label: { show: false },
    lineStyle: { color: colour, type: "dashed", width },
    data: [{ yAxis: level }],
  }
}
