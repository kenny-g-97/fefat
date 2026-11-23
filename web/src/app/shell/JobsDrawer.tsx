import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"
import { useCallback, useRef, useState } from "react"
import { isActive, type Job, jobsQuery } from "@/api/jobs"
import { Button } from "@/ui/button"
import { SectionFailure } from "@/ui/section-failure"
import { SheetClose, SheetContent, SheetTitle } from "@/ui/sheet"
import { JobRow } from "./JobRow"
import { usePointerLeaving } from "./pointer-leaving"

type JobsDrawerProps = Readonly<{ reconnecting: boolean }>

/** The jobs drawer (web/DESIGN.md, Patterns), which the top bar's indicator opens at the
 * window's right edge: the queued and running jobs first, then the ended, each newest first,
 * with its progress while it runs. */
export function JobsDrawer({ reconnecting }: JobsDrawerProps) {
  return (
    <SheetContent
      showCloseButton={false}
      aria-describedby={undefined}
      data-testid="jobs-drawer"
      className="gap-0"
    >
      <header className="flex h-18 shrink-0 items-center justify-between border-b px-6">
        <SheetTitle className="text-base">Jobs</SheetTitle>
        <SheetClose asChild>
          <Button
            data-slot="button"
            variant="ghost"
            size="icon-lg"
            aria-label="Close"
            title="Close"
          >
            <X className="size-5" />
          </Button>
        </SheetClose>
      </header>
      <JobList reconnecting={reconnecting} />
    </SheetContent>
  )
}

/** The rows, which hold their order and their number while the pointer is over the list, so that
 * a double click on one job's Cancel never lands on the next; each row's figures stay live, and a
 * new job shows once the pointer leaves. */
function JobList({ reconnecting }: JobsDrawerProps) {
  const jobs = useQuery(jobsQuery)
  const list = useRef<HTMLUListElement>(null)
  const [heldIds, setHeldIds] = useState<readonly string[] | null>(null)
  const letGo = useCallback(() => setHeldIds(null), [])
  usePointerLeaving(heldIds !== null, list, letGo)
  if (jobs.status === "pending") {
    return null
  }
  if (jobs.status === "error") {
    return (
      <SectionFailure
        error={jobs.error}
        onRetry={() => void jobs.refetch()}
        className="px-6 py-4"
      />
    )
  }
  if (jobs.data.length === 0) {
    return (
      <p className="px-6 py-4 text-foreground-secondary">
        No jobs yet. Imports, backtests, and studies show their progress here
        while they run.
      </p>
    )
  }
  const ordered = [
    ...jobs.data.filter(isActive),
    ...jobs.data.filter((job) => !isActive(job)),
  ]
  const shown = heldIds === null ? ordered : inHeldOrder(heldIds, ordered)
  return (
    <ul
      ref={list}
      data-testid="job-list"
      className="flex-1 overflow-y-auto px-6"
      onPointerEnter={() => setHeldIds(ordered.map((job) => job.id))}
      onPointerLeave={letGo}
    >
      {shown.map((job) => (
        <JobRow key={job.id} job={job} reconnecting={reconnecting} />
      ))}
    </ul>
  )
}

function inHeldOrder(
  heldIds: readonly string[],
  jobs: readonly Job[]
): readonly Job[] {
  const byId = new Map(jobs.map((job) => [job.id, job]))
  return heldIds.flatMap((id) => {
    const job = byId.get(id)
    return job === undefined ? [] : [job]
  })
}
