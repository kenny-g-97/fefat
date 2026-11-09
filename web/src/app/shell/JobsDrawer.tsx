import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"
import { jobsQuery } from "@/api/jobs"
import { Button } from "@/ui/button"
import { SheetClose, SheetContent, SheetTitle } from "@/ui/sheet"
import { JobRow } from "./JobRow"

/** The jobs drawer (web/DESIGN.md, Patterns), which the top bar's indicator opens at the
 * window's right edge: the newest jobs first, each with its progress while it runs. */
export function JobsDrawer() {
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
          <Button variant="outline" size="icon-lg" aria-label="Close">
            <X className="size-5" />
          </Button>
        </SheetClose>
      </header>
      <JobList />
    </SheetContent>
  )
}

function JobList() {
  const jobs = useQuery(jobsQuery)
  if (jobs.status === "pending") {
    return null
  }
  if (jobs.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 px-6 py-4">
        <p role="alert" className="text-negative">
          {jobs.error.message}
        </p>
        <Button variant="ghost" onClick={() => void jobs.refetch()}>
          Try again
        </Button>
      </div>
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
  return (
    <ul className="flex-1 overflow-y-auto px-6">
      {jobs.data.map((job) => (
        <JobRow key={job.id} job={job} />
      ))}
    </ul>
  )
}
