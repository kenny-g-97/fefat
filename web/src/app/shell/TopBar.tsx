import { useRouter } from "@tanstack/react-router"
import { Activity } from "lucide-react"
import { useCallback, useState } from "react"
import { useStoreReadAfterWrites } from "@/api/catalog"
import { failureWords, type Job, useJobEnds, useLiveJobs } from "@/api/jobs"
import { useRunsReadAfterBacktests } from "@/api/runs"
import { Button } from "@/ui/button"
import { Sheet, SheetTrigger } from "@/ui/sheet"
import { JobsDrawer } from "./JobsDrawer"

/** The shell's top bar (web/DESIGN.md, Patterns): 72 px over a hairline that meets the brand
 * row's, solid, holding the jobs indicator, whose count shows while jobs are queued or running,
 * whose dot shows a failure until the drawer opens, and which opens the jobs drawer. It follows
 * every job's progress for the whole app, says each job's end to a screen reader, reads again
 * what a catalog sync, an import, or a backtest wrote once it ends, on every page, and asks who
 * the browser is once a stream is refused, which leads a session that ended to the login. */
export function TopBar() {
  const router = useRouter()
  const readTheLoginAgain = useCallback(
    () => void router.invalidate(),
    [router]
  )
  const { jobs, streamNote } = useLiveJobs(readTheLoginAgain)
  useStoreReadAfterWrites(jobs.data)
  useRunsReadAfterBacktests(jobs.data)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [revealedJob, setRevealedJob] = useState<string | null>(null)
  const { failures, said, clearFailures } = useJobEnds(jobs.data, drawerOpen)
  const running = countOf(jobs.data, "running")
  const queued = countOf(jobs.data, "queued")
  const active = running + queued
  const label = jobsLabel(running, queued, failures)
  return (
    <header
      data-testid="top-bar"
      className="sticky top-0 z-10 flex h-18 shrink-0 items-center justify-end border-b bg-background px-6"
    >
      <p aria-live="polite" data-testid="jobs-said" className="sr-only">
        {said}
      </p>
      <Sheet
        modal={false}
        open={drawerOpen}
        onOpenChange={(open) => {
          setDrawerOpen(open)
          if (open) {
            setRevealedJob(failures.length > 0 ? failures[0].id : null)
            clearFailures()
          }
        }}
      >
        {/* A trigger's asChild gives the Button the trigger's own data-slot; this Button keeps
            the button's, which the stylesheet's rules key on. */}
        <SheetTrigger asChild>
          <Button
            data-slot="button"
            variant="outline"
            size="icon-lg"
            className="relative"
            aria-label={label}
            title={label}
            data-testid="jobs-indicator"
          >
            <Activity className="size-5" />
            {active > 0 && (
              <span
                aria-hidden="true"
                className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-xl bg-primary px-1.5 text-xs font-semibold text-primary-foreground ring-2 ring-background"
              >
                {active}
              </span>
            )}
            {failures.length > 0 && (
              <span
                aria-hidden="true"
                data-slot="jobs-failure-dot"
                data-testid="jobs-failure-dot"
                className="absolute right-1.5 bottom-1.5 size-2 rounded-xl bg-negative ring-2 ring-background"
              />
            )}
          </Button>
        </SheetTrigger>
        <JobsDrawer streamNote={streamNote} revealedJob={revealedJob} />
      </Sheet>
    </header>
  )
}

function countOf(
  jobs: readonly Job[] | undefined,
  status: Job["status"]
): number {
  return jobs === undefined
    ? 0
    : jobs.filter((job) => job.status === status).length
}

/** The indicator's name, for a screen reader and its `title`: `Jobs, 1 running, 2 queued`, then
 * any failure not yet seen, as `Backtest failed`. */
function jobsLabel(
  running: number,
  queued: number,
  failures: readonly Job[]
): string {
  const counts = [
    running > 0 ? `${running} running` : "",
    queued > 0 ? `${queued} queued` : "",
    failures.length > 0 ? failureWords(failures) : "",
  ].filter((count) => count !== "")
  return counts.length === 0 ? "Jobs" : `Jobs, ${counts.join(", ")}`
}
