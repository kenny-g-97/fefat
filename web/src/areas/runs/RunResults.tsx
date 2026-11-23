import { useQuery } from "@tanstack/react-query"
import { isRefusal } from "@/api/problems"
import { type RunStatistics, runStatisticsQuery } from "@/api/run-results"
import { SectionFailure } from "@/ui/section-failure"
import { BreakdownTables } from "./BreakdownTables"
import { DistributionsCard } from "./DistributionsCard"
import { EquityCard } from "./EquityCard"
import { FidelityCheckCard } from "./FidelityCheckCard"
import { KeyFigures } from "./KeyFigures"
import { RobustnessCard } from "./RobustnessCard"

/** A saved run's results (web/DESIGN.md, Patterns, Run page), every figure the API's: where the
 * server refuses them, as for a run another engine saved or a folder that is gone, its sentence
 * says why and what to do, in the results' place, the rest of the page keeping its status and
 * settings; any other failure offers Try again. */
export function RunResults({ runKey }: Readonly<{ runKey: string }>) {
  const statistics = useQuery(runStatisticsQuery(runKey))
  if (statistics.status === "pending") {
    return <div className="min-h-24" />
  }
  if (statistics.status === "error") {
    const refused =
      isRefusal(statistics.error, 404) || isRefusal(statistics.error, 409)
    return refused ? (
      <p
        role="alert"
        data-testid="run-results-refused"
        className="text-negative wrap-anywhere"
      >
        {statistics.error.message}
      </p>
    ) : (
      <SectionFailure
        error={statistics.error}
        onRetry={() => void statistics.refetch()}
      />
    )
  }
  return <ShownResults runKey={runKey} statistics={statistics.data} />
}

function ShownResults({
  runKey,
  statistics,
}: Readonly<{ runKey: string; statistics: RunStatistics }>) {
  const { metrics } = statistics
  return (
    <>
      <KeyFigures statistics={statistics} />
      <RobustnessCard
        robustness={metrics.robustness}
        trades={metrics.trades.trades}
      />
      <EquityCard runKey={runKey} drawdown={metrics.drawdown} />
      <BreakdownTables breakdowns={metrics.breakdowns} />
      {metrics.fidelity_check !== null &&
        metrics.fidelity_check !== undefined && (
          <FidelityCheckCard check={metrics.fidelity_check} />
        )}
      <DistributionsCard runKey={runKey} currency={statistics.currency} />
    </>
  )
}
