import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { useLocation, useNavigate, useSearch } from "@tanstack/react-router"
import { jobsQuery } from "@/api/jobs"
import { liveRun, runsQuery } from "@/api/runs"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { SectionFailure } from "@/ui/section-failure"
import { TextLink } from "@/ui/text-link"
import { RunFilters } from "./RunFilters"
import { RunHead, RunRow } from "./RunRow"
import type { RunsSearch } from "./run-search"

/** The Runs page (web/DESIGN.md, Patterns, Runs list): every backtest, newest first, its bar live
 * while it runs through the jobs' streams, narrowed by the filters in its address. */
export function RunsPage() {
  const filters = useSearch({ from: "/_shell/runs/" })
  const stressed = useLocation({
    select: (location) => location.state.stressed,
  })
  return (
    <Page
      title="Runs"
      description="Every backtest, newest first, with its status and how it went"
    >
      <div className="flex flex-col gap-6">
        {stressed !== undefined && (
          <p
            role="status"
            data-testid="runs-stressed"
            className="text-foreground-secondary"
          >
            {`Stress asked for ${stressed}: the base run, and the same at 1 and at 2 more ticks of slippage.`}
          </p>
        )}
        <Panel title="Backtests">
          <RunFilters filters={filters} />
          <RunList filters={filters} />
        </Panel>
      </div>
    </Page>
  )
}

function RunList({ filters }: Readonly<{ filters: RunsSearch }>) {
  const runs = useInfiniteQuery(runsQuery(filters))
  const jobs = useQuery(jobsQuery)
  const navigate = useNavigate({ from: "/runs/" })
  if (runs.status === "pending") {
    return <div className="min-h-24" />
  }
  if (runs.status === "error") {
    return (
      <SectionFailure
        error={runs.error}
        onRetry={() => void runs.refetch()}
        className="min-h-24 justify-center"
      />
    )
  }
  const listed = runs.data.pages.flatMap((page) => page.runs)
  if (listed.length === 0) {
    const asked = Object.values(filters).some((each) => each !== undefined)
    return asked ? (
      <div
        role="status"
        className="flex min-h-10 flex-wrap items-center justify-between gap-3"
      >
        <p className="text-foreground-secondary">
          No run matches these filters.
        </p>
        <Button variant="ghost" onClick={() => void navigate({ search: {} })}>
          Clear filters
        </Button>
      </div>
    ) : (
      <div className="flex flex-col items-start gap-3">
        <p className="text-foreground-secondary">
          No backtests yet. Open a strategy and press Run backtest.
        </p>
        <TextLink to="/strategies">Strategies</TextLink>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1">
      <RunHead />
      <ul className="-mx-0 flex flex-col gap-1">
        {listed.map((run) => (
          <RunRow key={run.id} run={liveRun(run, jobs.data)} />
        ))}
      </ul>
      {runs.hasNextPage && (
        <div className="flex justify-center pt-3">
          <Button
            variant="ghost"
            data-testid="runs-more"
            disabled={runs.isFetchingNextPage}
            onClick={() => void runs.fetchNextPage()}
          >
            Show more
          </Button>
        </div>
      )}
    </div>
  )
}
