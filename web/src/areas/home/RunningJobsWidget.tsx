import { useQuery } from "@tanstack/react-query"
import {
  isActive,
  isCancelling,
  type Job,
  jobsQuery,
  KIND_LABELS,
} from "@/api/jobs"
import { Button } from "@/ui/button"
import { Panel } from "@/ui/panel"
import { PercentBar } from "@/ui/percent-bar"

const EMPTY =
  "No jobs running. Imports, backtests, and studies show their progress here while they run."

/** Home's running jobs (web/DESIGN.md, Patterns): each queued or running job, its kind over its
 * bar with the percent, then its last message, live from the top bar's streams. A list it
 * cannot load fails here alone, with Try again, and the rest of the page keeps working. */
export function RunningJobsWidget() {
  return (
    <Panel title="Running jobs">
      <RunningJobs />
    </Panel>
  )
}

function RunningJobs() {
  const jobs = useQuery(jobsQuery)
  if (jobs.status === "pending") {
    return <div className="min-h-24" />
  }
  if (jobs.status === "error") {
    return (
      <div className="flex min-h-24 flex-col items-start justify-center gap-3">
        <p role="alert" className="text-negative">
          {jobs.error.message}
        </p>
        <Button variant="ghost" onClick={() => void jobs.refetch()}>
          Try again
        </Button>
      </div>
    )
  }
  const running = jobs.data.filter(isActive)
  if (running.length === 0) {
    return (
      <p className="flex min-h-24 items-center text-foreground-secondary">
        {EMPTY}
      </p>
    )
  }
  return (
    <ul className="flex min-h-24 flex-col gap-4">
      {running.map((job) => (
        <li
          key={job.id}
          data-testid="running-job"
          className="flex flex-col gap-2"
        >
          <span className="font-medium text-foreground">
            {KIND_LABELS[job.kind]}
          </span>
          <PercentBar
            value={job.progress}
            label={`${KIND_LABELS[job.kind]} progress`}
          />
          <JobNote job={job} />
        </li>
      ))}
    </ul>
  )
}

/** What a job does now: Queued until a worker takes it, Cancelling once asked to stop, or else
 * its last message. */
function JobNote({ job }: Readonly<{ job: Job }>) {
  const note = isCancelling(job)
    ? "Cancelling"
    : job.status === "queued"
      ? "Queued"
      : job.message
  if (note === null) {
    return null
  }
  return <p className="text-xs text-muted-foreground">{note}</p>
}
