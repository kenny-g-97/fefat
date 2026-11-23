import { useQuery } from "@tanstack/react-query"
import {
  isActive,
  isCancelling,
  type Job,
  jobsQuery,
  KIND_LABELS,
} from "@/api/jobs"
import { counted } from "@/ui/figures"
import { Panel } from "@/ui/panel"
import { PercentBar } from "@/ui/percent-bar"
import { SectionFailure } from "@/ui/section-failure"

/** How many jobs the card shows, so that a full pool never pushes the page down; the drawer
 * lists them all. */
const JOBS_SHOWN = 3
const EMPTY =
  "No jobs running. Imports, backtests, and studies show their progress here while they run."

/** Home's running jobs (web/DESIGN.md, Patterns): the first three queued or running jobs, each
 * its kind over its bar with the percent, then its last message, live from the top bar's
 * streams, then a line counting the rest, which the jobs drawer lists. A list it
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
  if (jobs.data === undefined) {
    return jobs.status === "error" ? (
      <SectionFailure
        error={jobs.error}
        onRetry={() => void jobs.refetch()}
        className="min-h-24 justify-center"
      />
    ) : (
      <div className="min-h-24" />
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
  const more = running.length - JOBS_SHOWN
  return (
    <ul className="flex min-h-24 flex-col gap-4">
      {running.slice(0, JOBS_SHOWN).map((job) => (
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
      {more > 0 && (
        <li
          data-testid="running-jobs-more"
          className="text-foreground-secondary"
        >
          {`${counted(more, "more job")} in the jobs drawer`}
        </li>
      )}
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
