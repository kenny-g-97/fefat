import { useQuery } from "@tanstack/react-query"
import { lazy, Suspense, useState } from "react"
import {
  type EquityCurve,
  type RunMetrics,
  runEquityQuery,
} from "@/api/run-results"
import { crosshairTime } from "@/charts/chart-time"
import { counted, formatFigure } from "@/ui/figures"
import { Panel } from "@/ui/panel"
import { QueryBody } from "@/ui/query-body"

// ECharts loads with the first finished run opened, out of the app's first bundle (D-93).
const EquityChart = lazy(async () => {
  const { EquityChart: chart } = await import("@/charts/EquityChart")
  return { default: chart }
})

type EquityCardProps = Readonly<{
  runKey: string
  drawdown: RunMetrics["drawdown"]
}>

/** The equity curve and its drawdown (web/DESIGN.md, Patterns, Equity chart): its figure is the
 * readout, the equity at the decision under the pointer, or else after the last. */
export function EquityCard({ runKey, drawdown }: EquityCardProps) {
  const equity = useQuery(runEquityQuery(runKey))
  return (
    <Panel title="Equity">
      <QueryBody query={equity}>
        {(curve) => <ShownCurve curve={curve} drawdown={drawdown} />}
      </QueryBody>
    </Panel>
  )
}

function ShownCurve({
  curve,
  drawdown,
}: Readonly<{ curve: EquityCurve; drawdown: RunMetrics["drawdown"] }>) {
  const [pointed, setPointed] = useState<number | null>(null)
  const last = curve.time.length - 1
  if (last < 0) {
    return (
      <p className="text-foreground-secondary">
        This run valued its account at no decision, so it has no curve.
      </p>
    )
  }
  const at = pointed === null ? last : pointed
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <p
          data-testid="equity-figure"
          className="text-3xl font-bold tracking-tight text-foreground"
        >
          {formatFigure(curve.equity[at])}
        </p>
        <p className="flex gap-4 text-foreground-secondary">
          <span data-testid="equity-time">{crosshairTime(curve.time[at])}</span>
          <span>
            Drawdown{" "}
            <span
              data-testid="equity-drawdown"
              className="font-semibold text-foreground"
            >
              {formatFigure(curve.drawdown[at])}
            </span>
          </span>
        </p>
      </div>
      <ul className="flex gap-5 text-xs text-foreground-secondary">
        <li className="flex items-center gap-2">
          <span className="size-2.5 rounded-xl bg-brand" />
          Equity
        </li>
        <li className="flex items-center gap-2">
          <span className="size-2.5 rounded-xl bg-input" />
          Drawdown
        </li>
      </ul>
      <div className="h-80">
        <Suspense fallback={<div className="h-full" />}>
          <EquityChart
            label="Equity and drawdown of this run. The arrow keys step through its decisions."
            curve={curve}
            pointed={pointed}
            onPointed={setPointed}
          />
        </Suspense>
      </div>
      {drawdown.peak !== null && drawdown.trough !== null && (
        <p data-testid="equity-spell" className="text-xs text-muted-foreground">
          {`Deepest fall from ${drawdown.peak} to ${drawdown.trough}. Longest spell under a peak: ${counted(drawdown.longest_drawdown_days, "day")}.`}
        </p>
      )}
    </div>
  )
}
