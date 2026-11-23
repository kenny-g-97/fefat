import { useCallback, useLayoutEffect, useRef, useState } from "react"
import {
  isActive,
  isCancelling,
  type Job,
  KIND_LABELS,
  runsAgain,
  useJobCancellation,
  useJobRunAgain,
} from "@/api/jobs"
import { Button } from "@/ui/button"
import { firstClick } from "@/ui/first-click"
import { formatInstant } from "@/ui/instant"
import { PercentBar } from "@/ui/percent-bar"
import { StatusBadge } from "@/ui/status-badge"
import { usePointerLeaving } from "./pointer-leaving"

type JobRowProps = Readonly<{ job: Job; reconnecting: boolean }>

/** A job in the jobs drawer (web/DESIGN.md, Patterns): its kind and status, then its bar and
 * Cancel while it is queued or running, or when it ended and why, with Run again unless it
 * succeeded, then its last message, or Reconnecting while its stream waits. A job that ends under
 * the pointer keeps Run again asleep until the pointer leaves the row, since Run again stands
 * where Cancel stood and a late second click would undo the Cancel. */
export function JobRow({ job, reconnecting }: JobRowProps) {
  const active = isActive(job)
  const row = useRef<HTMLLIElement>(null)
  const wasActive = useRef(active)
  const [endedUnderPointer, setEndedUnderPointer] = useState(false)
  const wake = useCallback(() => setEndedUnderPointer(false), [])
  useLayoutEffect(() => {
    if (wasActive.current && !active && row.current?.matches(":hover")) {
      setEndedUnderPointer(true)
    }
    wasActive.current = active
  }, [active])
  usePointerLeaving(endedUnderPointer, row, wake)
  const note = active && reconnecting ? "Reconnecting" : job.message
  return (
    <li
      ref={row}
      data-testid="job-row"
      className="flex flex-col gap-2 border-b py-4 last:border-b-0"
      onPointerLeave={wake}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-foreground">
          {KIND_LABELS[job.kind]}
        </span>
        <StatusBadge status={job.status} cancelling={isCancelling(job)} />
      </div>
      {active ? (
        <ActiveJob job={job} />
      ) : (
        <EndedJob job={job} asleep={endedUnderPointer} />
      )}
      {note !== null && <p className="text-xs text-muted-foreground">{note}</p>}
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

function EndedJob({ job, asleep }: Readonly<{ job: Job; asleep: boolean }>) {
  const runAgain = useJobRunAgain()
  return (
    <>
      <div className="flex min-h-8 items-center justify-between gap-3">
        {job.finished_at !== null && (
          <p className="text-xs text-muted-foreground">
            Ended {formatInstant(job.finished_at)}
          </p>
        )}
        {runsAgain(job) && runAgain.isSuccess && (
          <p
            data-testid="job-queued-again"
            className="text-xs text-muted-foreground"
          >
            Queued again
          </p>
        )}
        {runsAgain(job) && !runAgain.isSuccess && (
          <Button
            variant="ghost"
            size="sm"
            data-testid="job-run-again"
            disabled={asleep || runAgain.isPending}
            onClick={firstClick(() => runAgain.mutate(job.id))}
          >
            Run again
          </Button>
        )}
      </div>
      {job.error !== null && (
        <p
          data-testid="job-error"
          tabIndex={0}
          className="max-h-32 overflow-y-auto text-xs whitespace-pre-wrap text-negative wrap-anywhere"
        >
          {job.error}
        </p>
      )}
      {runAgain.error !== null && (
        <p role="alert" className="text-xs text-negative">
          {runAgain.error.message}
        </p>
      )}
    </>
  )
}
