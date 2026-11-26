import { lazyRouteComponent } from "@tanstack/react-router"
import { Suspense, useState } from "react"
import type { EquityFan } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { counted, formatCount, moneyFigure } from "@/ui/figures"

/** ECharts' chunk, loaded with the first Monte Carlo shown, out of the app's first bundle, as the
 * equity chart's is (`EquityCard`). */
const FanChart = lazyRouteComponent(
  () => import("@/charts/FanChart"),
  "FanChart"
)

type MonteCarloFanProps = Readonly<{
  fan: EquityFan
  trades: number
  currency: Currency
}>

/** The paths' equity fan (web/DESIGN.md, Patterns, Fan chart): its readout, the median after the
 * count of trades under the pointer, or else after the last, the run's own equity after as many
 * of its trades, and the middle half and nine in ten of the paths, three lines whatever the count,
 * so that it never moves the chart; the legend; and the chart. Its headline keeps clear of the
 * card's select of charts. */
export function MonteCarloFan({ fan, trades, currency }: MonteCarloFanProps) {
  const [pointed, setPointed] = useState<number | null>(null)
  const at = pointed === null ? fan.trades_made.length - 1 : pointed
  const money = (value: number) => moneyFigure(value, currency)
  return (
    <>
      <div className="flex flex-col gap-1">
        <p
          data-testid="fan-figure"
          className="pr-48 text-3xl font-bold tracking-tight text-foreground"
        >
          {money(fan.median[at])}
        </p>
        <p className="flex flex-wrap gap-x-4 text-foreground-secondary">
          <span data-testid="fan-count">
            {`Median after ${formatCount(fan.trades_made[at])} of ${counted(trades, "trade")}`}
          </span>
          <span>
            This run{" "}
            <span
              data-testid="fan-own"
              className="font-semibold text-foreground"
            >
              {money(fan.own[at])}
            </span>
          </span>
        </p>
        <p className="flex flex-wrap gap-x-4 text-foreground-secondary">
          <span>
            Middle 50%{" "}
            <span
              data-testid="fan-inner"
              className="font-semibold text-foreground"
            >
              {`${money(fan.p25[at])} to ${money(fan.p75[at])}`}
            </span>
          </span>
          <span>
            Middle 90%{" "}
            <span
              data-testid="fan-outer"
              className="font-semibold text-foreground"
            >
              {`${money(fan.p5[at])} to ${money(fan.p95[at])}`}
            </span>
          </span>
        </p>
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-foreground-secondary">
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-brand"
          />
          Median
        </li>
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-brand-secondary"
          />
          This run
        </li>
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-input/45 inset-ring-1 inset-ring-input"
          />
          Middle 50%
        </li>
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-input/30 inset-ring-1 inset-ring-input"
          />
          Middle 90%
        </li>
        <li className="flex items-center gap-2">
          <span className="w-4 border-t border-dashed border-foreground-secondary" />
          Capital
        </li>
      </ul>
      <div className="h-80">
        <Suspense fallback={<div className="h-full" />}>
          <FanChart
            label="Equity of the paths by trades made: the median, this run's own, and the middle half and nine in ten of the paths. The arrow keys step through the counts of trades."
            fan={fan}
            currency={currency}
            pointed={pointed}
            onPointed={setPointed}
          />
        </Suspense>
      </div>
    </>
  )
}
