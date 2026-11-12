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
import type { PriceFormat } from "@/charts/drawn-series"
import { usePageScrolls } from "@/ui/page-scroll"
import { SectionFailure } from "@/ui/section-failure"
import { ChartReadout } from "./ChartReadout"
import { chartPanes } from "./chart-panes"

/** Fewer bars than this before the view ask for the window before them. */
const PRELOAD_BARS = 500

type ChartViewProps = Readonly<{
  series: Series
  style: ChartStyle
  priceFormat: PriceFormat
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
  priceFormat,
  label,
  held,
}: ChartViewProps & Readonly<{ held: HeldDates }>) {
  const windows = useMemo(
    () => barWindows(held, series.timeframe),
    [held, series.timeframe]
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
  const bars = useMemo(() => joinedBars(read.map((each) => each?.bars)), [read])
  const panes = useMemo(
    () => chartPanes(bars, series.timeframe, style.volume_shown),
    [bars, series.timeframe, style.volume_shown]
  )
  const older = settled && wanted < windows.length
  const scrolls = usePageScrolls()
  const warnings = [...new Set(read.flatMap((each) => each?.warnings ?? []))]
  const loading = !settled || (older && visible.before < PRELOAD_BARS)

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
          "data-windows": `${read.filter((each) => each !== undefined).length} of ${windows.length}`,
          "data-before": String(visible.before),
          "data-after": String(visible.after),
          "data-panes": String(panes.length),
        }}
      >
        <ChartReadout
          bars={bars}
          index={hovered}
          decimals={priceFormat.precision}
          daily={series.timeframe === "1d"}
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

/** The windows asked for so far, newest first: each one's bars once read, whether every one is
 * read, and the first that failed. TanStack keeps `read` from one answer to the next while no
 * window's bars change, so that a year of bars is joined again only when they do. */
type ReadWindows = Readonly<{
  read: readonly (WindowBars | undefined)[]
  settled: boolean
  failure: Readonly<{ error: Error; retry: () => void }> | undefined
}>

function readWindows(
  results: readonly UseQueryResult<WindowBars>[]
): ReadWindows {
  const failed = results.find((result) => result.status === "error")
  return {
    read: results.map((result) => result.data),
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

/** The chart's card, which tells a test whether it is still loading and what it drew. */
function ChartFrame({
  loading = true,
  attributes = {},
  children,
}: ChartFrameProps) {
  return (
    <div
      data-testid="chart-view"
      data-loading={String(loading)}
      {...attributes}
      className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card shadow-raised"
    >
      {children}
    </div>
  )
}
