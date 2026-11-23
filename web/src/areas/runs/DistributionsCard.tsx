import { useQuery } from "@tanstack/react-query"
import {
  runDistributionsQuery,
  type TradeDistributions,
} from "@/api/run-results"
import { HistogramChart } from "@/charts/Histogram"
import { counted } from "@/ui/figures"
import { Panel } from "@/ui/panel"
import { ResultBody } from "./ResultBody"

/** How a run's trades spread (web/DESIGN.md, Patterns, Histogram): net P&L and the R multiple
 * either side of zero, the excursions in ticks, and the minutes held, every bin the server's. */
export function DistributionsCard({
  runKey,
  currency,
}: Readonly<{ runKey: string; currency: string }>) {
  const distributions = useQuery(runDistributionsQuery(runKey))
  return (
    <Panel title="Distributions">
      <ResultBody query={distributions}>
        {(shown) => <Histograms shown={shown} currency={currency} />}
      </ResultBody>
    </Panel>
  )
}

function Histograms({
  shown,
  currency,
}: Readonly<{ shown: TradeDistributions; currency: string }>) {
  if (shown.pnl.trades.length === 0) {
    return (
      <p
        data-testid="distributions-empty"
        className="text-foreground-secondary"
      >
        This run made no trade, so there is nothing to count.
      </p>
    )
  }
  const withoutStop = shown.trades_without_r_multiple
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-6">
        <HistogramChart
          testId="histogram-pnl"
          label={`Net P&L a trade, ${currency}`}
          bins={shown.pnl}
          signed
        />
        <HistogramChart
          testId="histogram-r_multiple"
          label="R multiple"
          note={
            withoutStop === 0
              ? undefined
              : `${counted(withoutStop, "trade")} without a stop left out`
          }
          bins={shown.r_multiple}
          signed
        />
      </div>
      <div className="grid grid-cols-3 gap-6">
        <HistogramChart
          testId="histogram-mae_ticks"
          label="Adverse excursion, ticks"
          bins={shown.mae_ticks}
        />
        <HistogramChart
          testId="histogram-mfe_ticks"
          label="Favourable excursion, ticks"
          bins={shown.mfe_ticks}
        />
        <HistogramChart
          testId="histogram-holding_minutes"
          label="Minutes held"
          bins={shown.holding_minutes}
        />
      </div>
    </div>
  )
}
