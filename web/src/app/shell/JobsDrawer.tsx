import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"
import { useCallback, useRef, useState } from "react"
import { isActive, jobsQuery } from "@/api/jobs"
import { Button } from "@/ui/button"
import { SectionFailure } from "@/ui/section-failure"
import { SheetClose, SheetContent, SheetTitle } from "@/ui/sheet"
import { JobRow } from "./JobRow"
import { usePointerLeaving } from "./pointer-leaving"

type JobsDrawerProps = Readonly<{
  streamNote: string | null
  revealedJob: string | null
}>

/** What the list holds still while the pointer is over it: its rows in order, and which of them
 * were under way, whose failure then keeps to one line. */
type Held = Readonly<{
  ids: readonly string[]
  active: ReadonlySet<string>
}>

/** The jobs drawer (web/DESIGN.md, Patterns), which the top bar's indicator opens at the
 * window's right edge: the queued and running jobs first, then the ended, each newest first,
 * with its progress while it runs, and the row of the first failure not yet seen in view. */
export function JobsDrawer({ streamNote, revealedJob }: JobsDrawerProps) {
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
      <JobList streamNote={streamNote} revealedJob={revealedJob} />
    </SheetContent>
  )
}

/** The rows, which hold their order, their number, and their place while the pointer is over the
 * list, so that a double click on one job's Cancel never lands on the next; each row's figures
 * stay live, and a new job shows once the pointer leaves. A read of the list that fails leaves
 * the rows it had, so that they can say they are reconnecting. */
function JobList({ streamNote, revealedJob }: JobsDrawerProps) {
  const jobs = useQuery(jobsQuery)
  const list = useRef<HTMLUListElement>(null)
  const [held, setHeld] = useState<Held | null>(null)
  const letGo = useCallback(() => setHeld(null), [])
  usePointerLeaving(held !== null, list, letGo)
  if (jobs.data === undefined) {
    return jobs.status === "error" ? (
      <SectionFailure
        error={jobs.error}
        onRetry={() => void jobs.refetch()}
        className="px-6 py-4"
      />
    ) : null
  }
  if (jobs.data.length === 0) {
    return (
      <p className="px-6 py-4 text-foreground-secondary">
        No jobs yet. Imports, backtests, and studies show their progress here
        while they run.
      </p>
    )
  }
  const active = jobs.data.filter(isActive)
  const ordered = [...active, ...jobs.data.filter((job) => !isActive(job))]
  const shown =
    held === null
      ? ordered
      : held.ids.flatMap((id) => ordered.find((job) => job.id === id) ?? [])
  return (
    <ul
      ref={list}
      data-testid="job-list"
      className="flex-1 overflow-y-auto px-6"
      onPointerEnter={() =>
        setHeld({
          ids: ordered.map((job) => job.id),
          active: new Set(active.map((job) => job.id)),
        })
      }
      onPointerLeave={letGo}
    >
      {shown.map((job) => (
        <JobRow
          key={job.id}
          job={job}
          streamNote={streamNote}
          listHeld={held !== null}
          errorHeld={held !== null && held.active.has(job.id)}
          revealed={job.id === revealedJob}
        />
      ))}
    </ul>
  )
}
