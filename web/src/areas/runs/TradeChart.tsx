import { useMemo } from "react"
import { barWindows, windowAt } from "@/api/bar-windows"
import type { ChartStyle } from "@/api/settings"
import type { Trade } from "@/api/trades"
import { ChartFrame } from "@/ui/chart-frame"
import { ChartWarnings } from "@/ui/chart-warnings"
import { SectionFailure } from "@/ui/section-failure"
import { useRunChartWindows } from "./run-chart-windows"
import { TRADE_CHART_FRAME } from "./trade-chart-frame"
import { TradeChartView } from "./TradeChartView"

type TradeChartProps = Readonly<{
  runKey: string
  dates: Readonly<{ first: string; last: string }>
  timeframe: string
  style: ChartStyle
  selected: Trade | null
}>

/** The trade review chart (web/DESIGN.md, Patterns, Trade review chart): the run's bars in its
 * strategy's timeframe, a window of its `dates` at a time around the selected trade's entry, or
 * the newest with none selected, drawn with every fill and the strategy's features once read;
 * its card says that its bars load until then, a window that fails to come says why with Try
 * again under the card, and what its pages warn of stands under it too. */
export function TradeChart({
  runKey,
  dates,
  timeframe,
  style,
  selected,
}: TradeChartProps) {
  const windows = useMemo(
    () => barWindows(dates, timeframe),
    [dates, timeframe]
  )
  const centre =
    selected === null ? 0 : windowAt(windows, selected.entry_trade_date)
  const read = useRunChartWindows(runKey, windows, centre)
  const loading = read.failure === undefined && !read.settled
  return (
    <>
      {read.chart === null ? (
        <ChartFrame {...TRADE_CHART_FRAME} loading={loading} />
      ) : (
        <TradeChartView
          chart={read.chart}
          timeframe={timeframe}
          style={style}
          selected={selected}
          loading={loading}
          onVisibleBarsChange={read.grow}
        />
      )}
      {read.failure !== undefined && (
        <SectionFailure
          error={read.failure.error}
          onRetry={read.failure.retry}
        />
      )}
      <ChartWarnings
        warnings={read.chart === null ? [] : read.chart.warnings}
      />
    </>
  )
}
