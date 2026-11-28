import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import {
  Link,
  useLocation,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import { ArrowRight } from "lucide-react"
import { useState } from "react"
import { jobsQuery } from "@/api/jobs"
import { liveRun, runsQuery, type SavedRun } from "@/api/runs"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { SectionFailure } from "@/ui/section-failure"
import { TextLink } from "@/ui/text-link"
import { RunFilters } from "./RunFilters"
import { RunHead, RunRow } from "./RunRow"
import { FEWEST_COMPARED, MOST_COMPARED, type RunsSearch } from "./run-search"
import { oldestFirst } from "./run-words"

/** The Runs page (web/DESIGN.md, Patterns, Runs list): every backtest, newest first, its bar live
 * while it runs through the jobs' streams, narrowed by the filters in its address; two to four saved
 * runs ticked open their comparison (step 5.10), the oldest the reference. */
export function RunsPage() {
  const filters = useSearch({ from: "/_shell/runs/" })
  const stressed = useLocation({
    select: (location) => location.state.stressed,
  })
  // The ticks belong to the filters they were made under, so that a run a change of the filters
  // takes out of sight is never compared; those filters bring them back until runs are ticked
  // under others.
  const asked = JSON.stringify(filters)
  const [ticked, setTicked] = useState<Ticked>({ under: asked, runs: [] })
  const chosen = ticked.under === asked ? ticked.runs : []
  const choose = (run: SavedRun, wanted: boolean) => {
    const others = chosen.filter((each) => each.run_key !== run.run_key)
    setTicked({ under: asked, runs: wanted ? [...others, run] : others })
  }
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
        <Panel
          title="Backtests"
          description={`Tick ${FEWEST_COMPARED} to ${MOST_COMPARED} saved runs to compare them side by side`}
          action={<CompareChosen chosen={chosen} filters={filters} />}
        >
          <RunFilters filters={filters} />
          <RunList filters={filters} chosen={chosen} onChoose={choose} />
        </Panel>
      </div>
    </Page>
  )
}

/** The runs ticked for a comparison, and the filters of the list they were ticked in. */
type Ticked = Readonly<{ under: string; runs: readonly SavedRun[] }>

/** Compare, a card's own action: a link to the comparison of the runs `chosen`, oldest first,
 * the reference, once two to four are; waiting otherwise. */
function CompareChosen({
  chosen,
  filters,
}: Readonly<{ chosen: readonly SavedRun[]; filters: RunsSearch }>) {
  if (chosen.length < FEWEST_COMPARED) {
    return (
      <Button
        variant="ghost"
        disabled
        data-testid="runs-compare"
        className="-my-2"
      >
        Compare
      </Button>
    )
  }
  return (
    <Button variant="ghost" asChild className="-my-2">
      <Link
        to="/runs/compare"
        search={{
          runs: oldestFirst(chosen)
            .map((run) => run.run_key)
            .join(","),
        }}
        state={{ runsFilters: filters }}
        data-testid="runs-compare"
      >
        {`Compare ${chosen.length} runs`}
        <ArrowRight className="size-4" />
      </Link>
    </Button>
  )
}

type RunListProps = Readonly<{
  filters: RunsSearch
  chosen: readonly SavedRun[]
  onChoose: (run: SavedRun, chosen: boolean) => void
}>

function RunList({ filters, chosen, onChoose }: RunListProps) {
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
        <Button
          variant="ghost"
          onClick={() => void navigate({ search: {}, state: true })}
        >
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
      <ul className="flex flex-col gap-1">
        {listed.map((run) => (
          <RunRow
            key={run.id}
            run={liveRun(run, jobs.data)}
            filters={filters}
            chosen={chosen.some(
              (each) => run.state === "saved" && each.run_key === run.run_key
            )}
            choosable={chosen.length < MOST_COMPARED}
            onChoose={onChoose}
          />
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
