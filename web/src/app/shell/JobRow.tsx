import {
  isActive,
  isCancelling,
  type Job,
  KIND_LABELS,
  useJobCancellation,
} from "@/api/jobs"
import { Button } from "@/ui/button"
import { formatInstant } from "@/ui/instant"
import { PercentBar } from "@/ui/percent-bar"
import { StatusBadge } from "@/ui/status-badge"

/** A job in the jobs drawer (web/DESIGN.md, Patterns): its kind and status, then its bar and
 * Cancel while it is queued or running, or when it ended and why, then its last message. */
export function JobRow({ job }: Readonly<{ job: Job }>) {
  return (
    <li
      data-testid="job-row"
      className="flex flex-col gap-2 border-b py-4 last:border-b-0"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-foreground">
          {KIND_LABELS[job.kind]}
        </span>
        <StatusBadge status={job.status} cancelling={isCancelling(job)} />
      </div>
      {isActive(job) ? <ActiveJob job={job} /> : <EndedJob job={job} />}
      {job.message !== null && (
        <p className="text-xs text-muted-foreground">{job.message}</p>
      )}
    </li>
  )
}

function ActiveJob({ job }: Readonly<{ job: Job }>) {
  const cancellation = useJobCancellation()
  return (
    <>
      <div className="flex min-h-8 items-center gap-3">
        <PercentBar
          value={job.progress}
          label={`${KIND_LABELS[job.kind]} progress`}
        />
        <Button
          variant="ghost"
          size="sm"
          data-testid="job-cancel"
          disabled={cancellation.isPending || isCancelling(job)}
          onClick={() => cancellation.mutate(job.id)}
        >
          Cancel
        </Button>
      </div>
      {cancellation.error !== null && (
        <p role="alert" className="text-xs text-negative">
          {cancellation.error.message}
        </p>
      )}
    </>
  )
}

function EndedJob({ job }: Readonly<{ job: Job }>) {
  return (
    <>
      {job.finished_at !== null && (
        <p className="flex min-h-8 items-center text-xs text-muted-foreground">
          Ended {formatInstant(job.finished_at)}
        </p>
      )}
      {job.error !== null && (
        <p className="text-xs text-negative">{job.error}</p>
      )}
    </>
  )
}
