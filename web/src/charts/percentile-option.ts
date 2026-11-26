import type { FigureAtPercents } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import type { ThemeTokens } from "./chart-look"
import {
  axisLabels,
  FONT,
  GRID_RIGHT,
  keptInView,
  labelStrip,
  NO_LINE,
  ownLine,
  pointerOptions,
  type ResultsChartOption,
  valueAxis,
} from "./results-chart"

/** The chart of a Monte Carlo's `figure` against the percent of its paths in the theme's `tokens`
 * (web/DESIGN.md, Patterns, Percentile chart), in the equity chart's idiom: the paths' figure in
 * the accent from the lowest path to the highest, a gap where a path has none, as one that drew no
 * losing trade has no profit factor, and the run's own as a dashed line in the purple (D-119),
 * kept in view; the value axis written as money in `currency`, or as plain figures where it is
 * null. Under them an unseen line holds a point at every percent, as the fan's unfilled base
 * does, so that the crosshair the keys place stands over a path without a figure too. Nothing
 * animates and there is no zoom; the pointer reads a percent, and its figures stand in the page's
 * own readout. */
export function percentileOption(
  figure: FigureAtPercents,
  currency: Currency | null,
  tokens: ThemeTokens
): ResultsChartOption {
  const atPercent: readonly (number | null)[] = figure.at_percent
  const held = atPercent.filter((value): value is number => value !== null)
  if (held.length === 0) {
    throw new Error(
      "Expected a figure of at least one path to chart, got none: say why in the chart's place."
    )
  }
  const own = figure.own
  const lowest = Math.min(...held)
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: {
      left: labelStrip(own === null ? held : [...held, own], currency),
      right: GRID_RIGHT,
      top: 8,
      bottom: 24,
      outerBoundsMode: "none",
    },
    ...pointerOptions(tokens),
    xAxis: {
      type: "value",
      min: 0,
      max: figure.at_percent.length - 1,
      interval: 10,
      axisLine: NO_LINE,
      axisTick: NO_LINE,
      splitLine: NO_LINE,
      axisLabel: {
        ...axisLabels(tokens),
        formatter: (percent: number) => `${percent}%`,
      },
    },
    yAxis: {
      ...valueAxis(tokens, currency),
      scale: true,
      ...(own === null ? {} : keptInView(own, lowest, Math.max(...held))),
    },
    series: [
      {
        type: "line",
        name: "Every percent",
        silent: true,
        symbol: "none",
        data: atPercent.map((_, percent) => [percent, lowest]),
        lineStyle: { opacity: 0 },
      },
      {
        type: "line",
        name: "Paths",
        symbol: "circle",
        showSymbol: false,
        data: figure.at_percent.map((value, percent) => [percent, value]),
        lineStyle: { color: tokens.brand, width: 1.5 },
        itemStyle: { color: tokens.brand },
        ...(own === null ? {} : { markLine: ownLine(own, tokens) }),
      },
    ],
  }
}
