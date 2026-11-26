import { useQuery } from "@tanstack/react-query"
import {
  Link,
  useLocation,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import { ArrowRight } from "lucide-react"
import { useEffect } from "react"
import { isActive, jobsQuery } from "@/api/jobs"
import { isRefusal } from "@/api/problems"
import {
  type ListedRun,
  liveRun,
  resultRunKey,
  runJobQuery,
  runQuery,
} from "@/api/runs"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { SectionFailure } from "@/ui/section-failure"
import { BackLink } from "@/ui/text-link"
import { RunResults } from "./RunResults"
import { RunParametersCard, RunSettingsCard } from "./RunSettingsCards"
import { RunStatusCard } from "./RunStatusCard"
import { RunStatusLine } from "./RunStatusLine"
import { foundWords, runLine } from "./run-words"

/** Back to the list, as the row that opened this run had it filtered. */
function BackToRuns() {
  const filters = useLocation({
    select: (location) => location.state.runsFilters,
  })
  return (
    <BackLink to="/runs" search={filters === undefined ? {} : filters}>
      Back to Runs
    </BackLink>
  )
}

const BACK = <BackToRuns />

/** The run's results in full (step 5.22), a page of its own: a ghost button, since it leads to
 * more of the same run rather than doing anything, its arrow saying that it leads to a page, as a
 * text link's does, carrying the way back to the list. */
function AllResultsLink({ runKey }: Readonly<{ runKey: string }>) {
  return (
    <Button variant="ghost" asChild>
      <Link
        to="/runs/run/results"
        search={{ key: runKey }}
        state={(kept) => kept}
        data-testid="all-results"
      >
        All results
        <ArrowRight className="size-4" />
      </Link>
    </Button>
  )
}

/** A run's page (web/DESIGN.md, Patterns, Run page), addressed by its run key once saved, or by
 * its row's id with its job while it runs: once saved, one line of its status, its results, and
 * the settings it ran under at the foot; while it runs, its status and progress over its
 * settings. Keyed by the run, since one route shows many. */
export function RunPage() {
  const { key, id, job } = useSearch({ from: "/_shell/runs/run" })
  const address = key === undefined ? id : key
  if (address === undefined) {
    return (
      <Page title="Run" back={BACK}>
        <p role="alert" className="text-negative">
          This address names no run. Choose one on the Runs page.
        </p>
      </Page>
    )
  }
  return <AddressedRun key={address} address={address} job={job} />
}

function AddressedRun({
  address,
  job,
}: Readonly<{ address: string; job: string | undefined }>) {
  const run = useQuery(runQuery(address))
  if (run.status === "pending") {
    return (
      <Page title="Run" back={BACK}>
        <div className="min-h-24" />
      </Page>
    )
  }
  if (run.status === "success") {
    return <ShownRun run={run.data} />
  }
  if (isRefusal(run.error, 404) && job !== undefined) {
    return <RunOfItsJob job={job} />
  }
  return (
    <Page title="Run" back={BACK}>
      {isRefusal(run.error, 404) ? (
        <p role="alert" className="text-negative">
          FEAT holds no such run. Choose one on the Runs page.
        </p>
      ) : (
        <SectionFailure error={run.error} onRetry={() => void run.refetch()} />
      )}
    </Page>
  )
}

/** A submission whose row gave way, its job having found the run saved under another row's key:
 * the page moves to that run, as found saved. */
function RunOfItsJob({ job }: Readonly<{ job: string }>) {
  const answer = useQuery(runJobQuery(job))
  const navigate = useNavigate()
  const runKey = answer.data === undefined ? null : resultRunKey(answer.data)
  useEffect(() => {
    if (runKey !== null) {
      void navigate({
        to: "/runs/run",
        search: { key: runKey },
        state: (kept) => ({ ...kept, cachedRun: runKey }),
        replace: true,
      })
    }
  }, [navigate, runKey])
  return (
    <Page title="Run" back={BACK}>
      {answer.status === "error" ? (
        <SectionFailure
          error={answer.error}
          onRetry={() => void answer.refetch()}
        />
      ) : answer.status === "success" &&
        runKey === null &&
        !isActive(answer.data) ? (
        <p role="alert" className="text-negative">
          This run is no longer held. Choose one on the Runs page.
        </p>
      ) : (
        <div className="min-h-24" />
      )}
    </Page>
  )
}

function ShownRun({ run }: Readonly<{ run: ListedRun }>) {
  const jobs = useQuery(jobsQuery)
  const navigate = useNavigate()
  const shown = liveRun(run, jobs.data)
  const cachedRun = useLocation({
    select: (location) => location.state.cachedRun,
  })
  const askedVersion = useLocation({
    select: (location) => location.state.askedVersion,
  })
  const addressedById = useSearch({
    from: "/_shell/runs/run",
    select: (search) => search.key === undefined,
  })
  const cached = shown.state === "saved" && cachedRun === shown.run_key
  const found = foundWords(shown, cached, askedVersion)
  const savedKey = run.state === "saved" ? run.run_key : null
  useEffect(() => {
    if (savedKey !== null && addressedById) {
      void navigate({
        to: "/runs/run",
        search: { key: savedKey },
        state: true,
        replace: true,
      })
    }
  }, [navigate, savedKey, addressedById])
  return (
    <Page
      title={shown.strategy === null ? "Run" : shown.strategy.name}
      description={runLine(shown)}
      back={BACK}
      action={
        shown.state === "saved" ? (
          <AllResultsLink runKey={shown.run_key} />
        ) : undefined
      }
    >
      {shown.state === "saved" ? (
        <div className="flex flex-col gap-6">
          <RunStatusLine run={shown} cached={cached} found={found} />
          <RunResults runKey={shown.run_key} strategy={shown.strategy} />
          <div className="grid grid-cols-[minmax(16rem,1fr)_auto] items-start gap-6">
            <RunParametersCard run={shown} />
            <RunSettingsCard run={shown} />
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start gap-6">
            <RunStatusCard run={shown} found={found} />
            <RunParametersCard run={shown} />
          </div>
          <RunSettingsCard run={shown} />
        </div>
      )}
    </Page>
  )
}
