import { Activity } from "lucide-react"
import { type Job, useLiveJobs } from "@/api/jobs"
import { Button } from "@/ui/button"
import { Sheet, SheetTrigger } from "@/ui/sheet"
import { JobsDrawer } from "./JobsDrawer"

/** The shell's top bar (web/DESIGN.md, Patterns): 72 px over a hairline that meets the brand
 * row's, solid, holding the jobs indicator, whose count shows while jobs are queued or running
 * and which opens the jobs drawer. It follows the active jobs' progress for the whole app. */
export function TopBar() {
  const jobs = useLiveJobs()
  const running = countOf(jobs.data, "running")
  const queued = countOf(jobs.data, "queued")
  const active = running + queued
  return (
    <header
      data-testid="top-bar"
      className="sticky top-0 z-10 flex h-18 shrink-0 items-center justify-end border-b bg-background px-6"
    >
      <Sheet modal={false}>
        {/* A trigger's asChild gives the Button the trigger's own data-slot; this Button keeps
            the button's, which the stylesheet's rules key on. */}
        <SheetTrigger asChild>
          <Button
            data-slot="button"
            variant="outline"
            size="icon-lg"
            className="relative"
            aria-label={jobsLabel(running, queued)}
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
          </Button>
        </SheetTrigger>
        <JobsDrawer />
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

/** The indicator's name for a screen reader: `Jobs, 1 running, 2 queued`. */
function jobsLabel(running: number, queued: number): string {
  const counts = [
    running > 0 ? `${running} running` : "",
    queued > 0 ? `${queued} queued` : "",
  ].filter((count) => count !== "")
  return counts.length === 0 ? "Jobs" : `Jobs, ${counts.join(", ")}`
}
