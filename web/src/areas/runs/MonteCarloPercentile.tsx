import { lazyRouteComponent } from "@tanstack/react-router"
import { Suspense, useState } from "react"
import type { FigureAtPercents, PathFigure } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { sentenceCase } from "@/ui/figures"
import {
  NO_OWN_PROFIT_FACTOR,
  NO_PATH_PROFIT_FACTOR,
  PATH_FIGURES,
  pathFigureWritten,
  percentWords,
} from "./result-words"

/** ECharts' chunk, the one the fan loads (`MonteCarloFan`). */
const PercentileChart = lazyRouteComponent(
  () => import("@/charts/PercentileChart"),
  "PercentileChart"
)

/** The percent whose path the readout shows while nothing is pointed at: the median path. */
const RESTING_PERCENT = 50

type MonteCarloPercentileProps = Readonly<{
  figure: PathFigure
  shown: FigureAtPercents
  currency: Currency
}>

/** One figure of the paths against the percent of them (web/DESIGN.md, Patterns, Percentile
 * chart): its readout, the figure of the path at the percent under the pointer, or else of the
 * median path, where the paths stand there, and the run's own; the legend; and the chart, or
 * where no path has the figure, why. Its headline keeps clear of the card's select of charts. */
export function MonteCarloPercentile({
  figure,
  shown,
  currency,
}: MonteCarloPercentileProps) {
  const [pointed, setPointed] = useState<number | null>(null)
  const at = pointed === null ? RESTING_PERCENT : pointed
  const value = shown.at_percent[at]
  const { inWords, unit } = PATH_FIGURES[figure]
  return (
    <>
      <div className="flex flex-col gap-1">
        <p
          data-testid="percentile-figure"
          className="pr-48 text-3xl font-bold tracking-tight text-foreground"
        >
          {pathFigureWritten(figure, value, currency)}
        </p>
        <p data-testid="percentile-words" className="text-foreground-secondary">
          {percentWords(figure, at, value)}
        </p>
        <p data-testid="percentile-own" className="text-foreground-secondary">
          {shown.own === null ? (
            NO_OWN_PROFIT_FACTOR
          ) : (
            <>
              This run{" "}
              <span className="font-semibold text-foreground">
                {pathFigureWritten(figure, shown.own, currency)}
              </span>
            </>
          )}
        </p>
      </div>
      <ul className="flex gap-5 text-xs text-foreground-secondary">
        <li className="flex items-center gap-2">
          <span
            data-slot="chart-mark"
            className="size-2.5 rounded-xl bg-brand"
          />
          Paths
        </li>
        {shown.own !== null && (
          <li className="flex items-center gap-2">
            <span className="w-4 border-t-2 border-dashed border-brand-secondary" />
            This run
          </li>
        )}
      </ul>
      <div className="h-80">
        {shown.at_percent.every((each) => each === null) ? (
          <p
            data-testid="percentile-none"
            className="text-foreground-secondary"
          >
            {NO_PATH_PROFIT_FACTOR}
          </p>
        ) : (
          <Suspense fallback={<div className="h-full" />}>
            <PercentileChart
              label={`${sentenceCase(inWords)} of the paths at each percent of them, beside this run's. The arrow keys step through the percents.`}
              figure={shown}
              currency={unit === "money" ? currency : null}
              rest={RESTING_PERCENT}
              pointed={pointed}
              onPointed={setPointed}
            />
          </Suspense>
        )}
      </div>
    </>
  )
}
