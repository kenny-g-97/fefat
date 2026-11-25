import { useState } from "react"
import type { MonteCarlo } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { Picker } from "@/ui/picker"
import { MonteCarloFan } from "./MonteCarloFan"
import { MonteCarloPercentile } from "./MonteCarloPercentile"
import {
  chartNamed,
  MONTE_CARLO_CHARTS,
  type MonteCarloChart,
  monteCarloNote,
} from "./result-words"

/** The Monte Carlo card's charts (web/DESIGN.md, Patterns, Monte Carlo card): the chart a select
 * at the right of its headline chooses, the paths' equity fan with the run's own walk over it, or
 * one of their figures against the percent of them, and under it the note on what was drawn. The
 * select stands apart from the charts it changes, so that it keeps the focus as a chart gives way
 * to another. */
export function MonteCarloCharts({
  report,
  currency,
}: Readonly<{ report: MonteCarlo; currency: Currency }>) {
  const [chart, setChart] = useState<MonteCarloChart>("equity")
  return (
    <div className="relative flex flex-col gap-4">
      <div className="absolute top-0 right-0">
        <Picker
          id="monte-carlo-chart"
          label="Chart"
          value={chart}
          options={MONTE_CARLO_CHARTS}
          onChange={(value) => setChart(chartNamed(value))}
          className="w-44"
        />
      </div>
      {chart === "equity" ? (
        <MonteCarloFan
          fan={report.fan}
          trades={report.trades}
          currency={currency}
        />
      ) : (
        <MonteCarloPercentile
          key={chart}
          figure={chart}
          shown={report.by_percent[chart]}
          currency={currency}
        />
      )}
      <p
        data-testid="monte-carlo-note"
        className="text-xs text-muted-foreground"
      >
        {monteCarloNote(report)}
      </p>
    </div>
  )
}
