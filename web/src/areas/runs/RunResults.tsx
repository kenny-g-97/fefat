import { useQuery } from "@tanstack/react-query"
import { type RunStatistics, runStatisticsQuery } from "@/api/run-results"
import type { SavedRun } from "@/api/runs"
import { TextLink } from "@/ui/text-link"
import { BreakdownTables } from "./BreakdownTables"
import { DistributionsCard } from "./DistributionsCard"
import { EquityCard } from "./EquityCard"
import { FidelityCheckCard } from "./FidelityCheckCard"
import { KeyFigures } from "./KeyFigures"
import { ResultBody } from "./ResultBody"
import { RobustnessCard } from "./RobustnessCard"

type RunResultsProps = Readonly<{
  runKey: string
  strategy: SavedRun["strategy"]
}>

/** A saved run's results (web/DESIGN.md, Patterns, Run page), every figure the API's: room for
 * them while they load, so that the cards at the foot do not jump; where the server refuses them,
 * its sentence in their place, with the way back to the run's version. */
export function RunResults({ runKey, strategy }: RunResultsProps) {
  const statistics = useQuery(runStatisticsQuery(runKey))
  if (statistics.status === "pending") {
    return <div className="min-h-screen" />
  }
  return (
    <ResultBody
      query={statistics}
      afterRefusal={
        strategy !== null && (
          <TextLink
            to="/strategies/strategy"
            search={{ name: strategy.name, version: strategy.version }}
          >
            Back to its version
          </TextLink>
        )
      }
    >
      {(answered) => <ShownResults runKey={runKey} statistics={answered} />}
    </ResultBody>
  )
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
