import { useQuery } from "@tanstack/react-query"
import { useSearch } from "@tanstack/react-router"
import {
  type RunStatistics,
  runResultsBySideQuery,
  runStatisticsQuery,
} from "@/api/run-results"
import { runQuery } from "@/api/runs"
import { Page } from "@/ui/page"
import { BackLink } from "@/ui/text-link"
import { KeyFigures } from "./KeyFigures"
import { ResultBody } from "./ResultBody"
import { ResultsBySideCard } from "./ResultsBySideCard"
import { RunKey } from "./RunStatusLine"
import { resultsLine } from "./run-words"

const TITLE = "All results"

/** A saved run's results in full (web/DESIGN.md, Patterns, All results page), addressed by its run
 * key: the eight KPI cards as its page shows them, then its figures for all, long, and short
 * trades, led back to the run. */
export function AllResultsPage() {
  const { key } = useSearch({ from: "/_shell/runs/run_/results" })
  if (key === undefined) {
    return (
      <Page title={TITLE} back={<BackLink to="/runs">Back to Runs</BackLink>}>
        <p role="alert" className="text-negative">
          This address names no run. Choose one on the Runs page.
        </p>
      </Page>
    )
  }
  return <ResultsOfRun key={key} runKey={key} />
}

/** The page of the saved run `runKey`: its line once its row answers, its key, which tells it
 * apart from another run of the version on the window, room for its figures while they load, and
 * the server's sentence in their place where it refuses them. */
function ResultsOfRun({ runKey }: Readonly<{ runKey: string }>) {
  const run = useQuery(runQuery(runKey))
  const statistics = useQuery(runStatisticsQuery(runKey))
  return (
    <Page
      title={TITLE}
      description={run.data === undefined ? undefined : resultsLine(run.data)}
      back={
        <BackLink
          to="/runs/run"
          search={{ key: runKey }}
          state={(kept) => kept}
        >
          Back to the run
        </BackLink>
      }
    >
      <div className="flex flex-col gap-6">
        <RunKey runKey={runKey} />
        {statistics.status === "pending" ? (
          <div className="min-h-screen" />
        ) : (
          <ResultBody query={statistics}>
            {(answered) => (
              <ResultsInFull runKey={runKey} statistics={answered} />
            )}
          </ResultBody>
        )}
      </div>
    </Page>
  )
}

function ResultsInFull({
  runKey,
  statistics,
}: Readonly<{ runKey: string; statistics: RunStatistics }>) {
  const sides = useQuery(runResultsBySideQuery(runKey))
  return (
    <div className="flex flex-col gap-6">
      <KeyFigures statistics={statistics} />
      <ResultBody query={sides}>
        {(answered) => (
          <ResultsBySideCard
            results={answered}
            currency={statistics.currency}
          />
        )}
      </ResultBody>
    </div>
  )
}
