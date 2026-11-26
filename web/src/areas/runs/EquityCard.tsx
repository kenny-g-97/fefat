import { useQuery } from "@tanstack/react-query"
import { lazyRouteComponent } from "@tanstack/react-router"
import { Suspense, useState } from "react"
import {
  type EquityCurve,
  type RunMetrics,
  runEquityQuery,
} from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { crosshairTime } from "@/charts/chart-time"
import { counted, moneyFigure } from "@/ui/figures"
import { Panel } from "@/ui/panel"
import { ResultBody } from "./ResultBody"

/** ECharts' chunk, loaded with the first finished run opened, out of the app's first bundle
 * (D-93); a chunk a rebuild of the web app has replaced reloads the page once, where React's
 * `lazy` would keep its first failure. */
const EquityChart = lazyRouteComponent(
  () => import("@/charts/EquityChart"),
  "EquityChart"
)

const SECONDS_A_MINUTE = 60

type EquityCardProps = Readonly<{
  runKey: string
  drawdown: RunMetrics["drawdown"]
  currency: Currency
}>

/** The equity curve and its drawdown in `currency` (web/DESIGN.md, Patterns, Equity chart): its
 * figure is the readout, the equity at the decision under the pointer, or else after the last. */
export function EquityCard({ runKey, drawdown, currency }: EquityCardProps) {
  const equity = useQuery(runEquityQuery(runKey))
  return (
    <Panel title="Equity">
      <ResultBody query={equity}>
        {(curve) => (
          <ShownCurve curve={curve} drawdown={drawdown} currency={currency} />
        )}
      </ResultBody>
    </Panel>
  )
}

function ShownCurve({
  curve,
  drawdown,
  currency,
}: Readonly<{
  curve: EquityCurve
  drawdown: RunMetrics["drawdown"]
  currency: Currency
}>) {
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
  const inSeconds = curve.time.some((time) => time % SECONDS_A_MINUTE !== 0)
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <p
          data-testid="equity-figure"
          className="text-3xl font-bold tracking-tight text-foreground"
        >
          {moneyFigure(curve.equity[at], currency)}
        </p>
        <p className="flex gap-4 text-foreground-secondary">
          <span data-testid="equity-time">
            {crosshairTime(curve.time[at], inSeconds)}
          </span>
          <span>
            Drawdown{" "}
            <span
              data-testid="equity-drawdown"
              className="font-semibold text-foreground"
            >
              {moneyFigure(curve.drawdown[at], currency)}
            </span>
          </span>
        </p>
      </div>
      <ul
        data-testid="equity-legend"
        className="flex gap-5 text-xs text-foreground-secondary"
      >
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-positive"
          />
          Above the capital
        </li>
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-negative"
          />
          Below the capital
        </li>
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-input"
          />
          Drawdown
        </li>
        <li className="flex items-center gap-2">
          <span className="w-4 border-t border-dashed border-foreground-secondary" />
          Capital
        </li>
      </ul>
      <div className="h-80">
        <Suspense fallback={<div className="h-full" />}>
          <EquityChart
            label="Equity and drawdown of this run. The arrow keys step through its decisions."
            curve={curve}
            currency={currency}
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
