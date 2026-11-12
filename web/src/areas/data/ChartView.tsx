import {
  type UseQueryResult,
  useQueries,
  useQuery,
} from "@tanstack/react-query"
import { type ReactNode, useMemo, useState } from "react"
import { barWindows, type HeldDates, joinedBars } from "@/api/bar-windows"
import {
  barsSpanQuery,
  barsWindowQuery,
  type Series,
  type WindowBars,
} from "@/api/bars"
import type { ChartStyle } from "@/api/settings"
import { PriceChart, type VisibleBars } from "@/charts/PriceChart"
import { decimalsOf } from "@/ui/figures"
import { usePageScrolls } from "@/ui/page-scroll"
import { SectionFailure } from "@/ui/section-failure"
import { ChartReadout } from "./ChartReadout"
import { chartPanes } from "./chart-panes"

/** Fewer bars than this before the view ask for the window before them. */
const PRELOAD_BARS = 500

type ChartViewProps = Readonly<{
  series: Series
  style: ChartStyle
  tickSize: number
  label: string
}>

/** A series' chart: the trade dates its data holds and the provider that holds them, then its
 * bars a window at a time from that provider, the newest first and each older one as the view
 * nears the oldest bar loaded; or why the store cannot give the series, in the SDK's words. */
export function ChartView(props: ChartViewProps) {
  const span = useQuery(barsSpanQuery(props.series))
  if (span.status === "pending") {
    return <ChartFrame />
  }
  if (span.status === "error") {
    return (
      <SectionFailure error={span.error} onRetry={() => void span.refetch()} />
    )
  }
  if (span.data.held === null) {
    return (
      <p className="text-foreground-secondary">
        No bars of {props.series.instrument} in the store at{" "}
        {props.series.timeframe}.
      </p>
    )
  }
  // An import between two windows could change the recommended provider for the later one.
  const series = { ...props.series, provider: span.data.provider }
  return <ChartWindows {...props} series={series} held={span.data.held} />
}

function ChartWindows({
  series,
  style,
  tickSize,
  label,
  held,
}: ChartViewProps & Readonly<{ held: HeldDates }>) {
  const windows = useMemo(
    () => barWindows(held, series.timeframe),
    [held, series.timeframe]
  )
  const priceFormat = useMemo(
    () => ({ precision: decimalsOf(tickSize), minMove: tickSize }),
    [tickSize]
  )
  const [wanted, setWanted] = useState(1)
  const [hovered, setHovered] = useState<number | null>(null)
  const [visible, setVisible] = useState<VisibleBars>({ before: 0, after: 0 })
  const { read, settled, failure } = useQueries({
    queries: windows
      .slice(0, wanted)
      .map((window) => barsWindowQuery(series, window)),
    combine: readWindows,
  })
  const bars = useMemo(() => joinedBars(read.map((each) => each.bars)), [read])
  const panes = useMemo(
    () => chartPanes(bars, series.timeframe, style.volume_shown),
    [bars, series.timeframe, style.volume_shown]
  )
  const older = settled && wanted < windows.length
  const scrolls = usePageScrolls()
  const warnings = [...new Set(read.flatMap((each) => each.warnings))]
  const loading =
    failure === undefined &&
    (!settled || (older && visible.before < PRELOAD_BARS))

  const moved = (bars: VisibleBars) => {
    setVisible(bars)
    if (older && bars.before < PRELOAD_BARS) {
      setWanted(wanted + 1)
    }
  }

  return (
    <>
      <ChartFrame
        loading={loading}
        attributes={{
          "data-bars": String(bars.time.length),
          "data-first-date": bars.trade_date.at(0) ?? "",
          "data-windows": `${read.length} of ${windows.length}`,
          "data-before": String(visible.before),
          "data-after": String(visible.after),
        }}
      >
        <ChartReadout
          bars={bars}
          index={hovered}
          decimals={priceFormat.precision}
          daily={series.timeframe === "1d"}
          loading={loading}
        />
        <PriceChart
          label={label}
          panes={panes}
          style={style}
          priceFormat={priceFormat}
          wheel={scrolls ? "page" : "chart"}
          onVisibleBarsChange={moved}
          onCrosshairMove={setHovered}
        />
      </ChartFrame>
      {failure !== undefined && (
        <SectionFailure error={failure.error} onRetry={failure.retry} />
      )}
      {warnings.length > 0 && (
        <ul className="flex shrink-0 flex-col gap-1 text-xs text-foreground-secondary">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </>
  )
}

/** The windows asked for so far: the bars of those read in a row from the newest, whether every
 * one is read, and the first that failed. TanStack keeps `read` from one answer to the next while
 * no window joins it, a window asked for and not yet read included, so that a year of bars is
 * joined and drawn again only when a window's bars arrive. */
type ReadWindows = Readonly<{
  read: readonly WindowBars[]
  settled: boolean
  failure: Readonly<{ error: Error; retry: () => void }> | undefined
}>

function readWindows(
  results: readonly UseQueryResult<WindowBars>[]
): ReadWindows {
  const waiting = results.findIndex((result) => result.data === undefined)
  const failed = results.find((result) => result.status === "error")
  return {
    read: results
      .slice(0, waiting === -1 ? results.length : waiting)
      .flatMap((result) => (result.data === undefined ? [] : [result.data])),
    settled: results.every((result) => result.status === "success"),
    failure:
      failed === undefined
        ? undefined
        : { error: failed.error, retry: () => void failed.refetch() },
  }
}

type ChartFrameProps = Readonly<{
  loading?: boolean
  attributes?: Readonly<Record<`data-${string}`, string>>
  children?: ReactNode
}>

/** The chart's card, busy while bars load, which tells a test whether it is still loading and
 * what it drew; before its first bars, it says that they load. */
function ChartFrame({
  loading = true,
  attributes = {},
  children,
}: ChartFrameProps) {
  return (
    <div
      data-testid="chart-view"
      data-loading={String(loading)}
      aria-busy={loading}
      {...attributes}
      className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card shadow-raised"
    >
      {children === undefined ? (
        <p className="flex min-h-12 items-center border-b px-4 text-xs text-muted-foreground">
          Loading bars
        </p>
      ) : (
        children
      )}
    </div>
  )
}
