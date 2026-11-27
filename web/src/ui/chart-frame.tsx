import type { ReactNode } from "react"
import { CHART_FRAME, useChartFrameSize } from "./chart-frame-size"
import type { FrameSize } from "./frame-size"
import { ResizableFrame } from "./resizable-frame"

export type ChartFrameProps = Readonly<{
  keptAs: string
  fallback: FrameSize
  loading?: boolean
  attributes?: Readonly<Record<`data-${string}`, string>>
  children?: ReactNode
}>

/** A chart's card, busy while bars load, which tells a test whether it is still loading and
 * what it drew; before its first bars, it says that they load. It stands in a frame the trader
 * sizes by its edges (web/DESIGN.md, Patterns, Resizable frame), kept in this browser under
 * `keptAs`, `fallback` until the trader sizes it, while bars load too, so that the card they
 * arrive in is the size it was. */
export function ChartFrame({
  keptAs,
  fallback,
  loading = true,
  attributes = {},
  children,
}: ChartFrameProps) {
  const [size, resize] = useChartFrameSize(keptAs, fallback)
  return (
    <ResizableFrame
      label="Chart"
      size={size}
      onResize={resize}
      leastWidth={CHART_FRAME.leastWidth}
      leastHeight={CHART_FRAME.leastHeight}
      mostHeight={CHART_FRAME.mostHeight}
    >
      <div
        data-testid="chart-view"
        data-loading={String(loading)}
        aria-busy={loading}
        {...attributes}
        className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card shadow-raised"
      >
        {children === undefined ? (
          <p className="box-content flex min-h-10 items-center border-b px-4 py-2 text-xs text-muted-foreground">
            Loading bars
          </p>
        ) : (
          children
        )}
      </div>
    </ResizableFrame>
  )
}
