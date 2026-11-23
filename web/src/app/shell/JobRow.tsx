import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import {
  isActive,
  isCancelling,
  type Job,
  jobsQuery,
  KIND_LABELS,
  runsAgain,
  STATUS_LABELS,
  useJobCancellation,
  useJobRunAgain,
} from "@/api/jobs"
import { Button } from "@/ui/button"
import { firstClick } from "@/ui/first-click"
import { formatInstant } from "@/ui/instant"
import { PercentBar } from "@/ui/percent-bar"
import { StatusBadge } from "@/ui/status-badge"

type JobRowProps = Readonly<{
  job: Job
  streamNote: string | null
  listHeld: boolean
  errorHeld: boolean
  revealed: boolean
}>

/** A job in the jobs drawer (web/DESIGN.md, Patterns): its kind and status; then its bar and
 * Cancel while it is queued or running, or once it ended Run again at the left, unless it
 * succeeded, and when it ended at the right, so that a late click meant for Cancel lands on plain
 * text; then why it failed; then one last line, its message or what its stream is doing. A
 * failure that arrives while the list is held stands cut to that line, so that no row moves, and
 * opens once the pointer leaves. */
export function JobRow({
  job,
  streamNote,
  listHeld,
  errorHeld,
  revealed,
}: JobRowProps) {
  const row = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (revealed) {
      row.current?.scrollIntoView({ block: "nearest" })
    }
  }, [revealed])
  const active = isActive(job)
  const heldError = errorHeld ? job.error : null
  const note = active && streamNote !== null ? streamNote : job.message
  return (
    <li
      ref={row}
      data-testid="job-row"
      className="flex flex-col gap-2 border-b py-4 last:border-b-0"
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
        <EndedJob
          job={job}
          listHeld={listHeld}
          showsError={heldError === null}
        />
      )}
      {heldError === null ? (
        <p
          title={note === null ? undefined : note}
          className="min-h-4 truncate text-xs text-muted-foreground"
        >
          {note}
        </p>
      ) : (
        <p
          data-testid="job-held-error"
          title={heldError}
          className="min-h-4 truncate text-xs text-negative"
        >
          {heldError}
        </p>
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
          onClick={firstClick(() => cancellation.mutate(job.id))}
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

/** When the job ended and why, with Run again, which reads Queued again or Running again while
 * the job it started is under way, then how that job ended for as long as the list is held, whose
 * row it holds back, and offers itself again after that; a press from the keyboard moves the focus
 * to those words, and back to Run again when they leave. */
function EndedJob({
  job,
  listHeld,
  showsError,
}: Readonly<{ job: Job; listHeld: boolean; showsError: boolean }>) {
  const runAgain = useJobRunAgain()
  const jobs = useQuery(jobsQuery)
  const pressedByKey = useRef(false)
  const wordsHeldFocus = useRef(false)
  const words = useRef<HTMLParagraphElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const answered = runAgain.data
  const listed = jobs.data?.find((each) => each.id === answered?.id)
  const rerun = listed === undefined ? answered : listed
  const again = againWords(rerun, listHeld)
  useEffect(() => {
    if (again !== null && pressedByKey.current) {
      pressedByKey.current = false
      wordsHeldFocus.current = true
      words.current?.focus()
    } else if (again === null && wordsHeldFocus.current) {
      wordsHeldFocus.current = false
      if (document.activeElement === document.body) {
        button.current?.focus()
      }
    }
  }, [again])
  return (
    <>
      <div className="flex min-h-8 items-center gap-3">
        {runsAgain(job) && again !== null && (
          <p
            ref={words}
            tabIndex={-1}
            data-testid="job-queued-again"
            className="text-xs text-muted-foreground"
          >
            {again}
          </p>
        )}
        {runsAgain(job) && again === null && (
          <Button
            ref={button}
            variant="ghost"
            size="sm"
            className="-ml-3"
            data-testid="job-run-again"
            disabled={runAgain.isPending}
            onClick={(event) => {
              pressedByKey.current = event.detail === 0
              firstClick(() => runAgain.mutate(job.id))(event)
            }}
          >
            Run again
          </Button>
        )}
        {job.finished_at !== null && (
          <p className="ml-auto text-xs text-muted-foreground">
            Ended {formatInstant(job.finished_at)}
          </p>
        )}
      </div>
      {runAgain.error !== null && (
        <p role="alert" className="text-xs text-negative">
          {runAgain.error.message}
        </p>
      )}
      {showsError && job.error !== null && (
        <p
          data-testid="job-error"
          tabIndex={0}
          className="max-h-34 overflow-y-auto text-xs whitespace-pre-wrap text-negative wrap-anywhere"
        >
          {job.error}
        </p>
      )}
    </>
  )
}

/** What stands in Run again's place once it was pressed: how far the job it started has come,
 * then how that job ended while the list holds its new row back. */
function againWords(rerun: Job | undefined, listHeld: boolean): string | null {
  if (rerun === undefined) {
    return null
  }
  if (isActive(rerun)) {
    return `${STATUS_LABELS[rerun.status]} again`
  }
  return listHeld
    ? `Ran again: ${STATUS_LABELS[rerun.status].toLowerCase()}`
    : null
}
