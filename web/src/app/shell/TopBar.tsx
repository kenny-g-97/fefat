import { Activity } from "lucide-react"
import { isActive, useLiveJobs } from "@/api/jobs"
import { Button } from "@/ui/button"
import { Sheet, SheetTrigger } from "@/ui/sheet"
import { JobsDrawer } from "./JobsDrawer"

/** The shell's top bar (web/DESIGN.md, Patterns): 72 px over a hairline that meets the brand
 * row's, solid, holding the jobs indicator, whose count shows while jobs are queued or running
 * and which opens the jobs drawer. It follows the active jobs' progress for the whole app. */
export function TopBar() {
  const jobs = useLiveJobs()
  const active = jobs.data === undefined ? 0 : jobs.data.filter(isActive).length
  return (
    <header className="sticky top-0 z-10 flex h-18 shrink-0 items-center justify-end border-b bg-background px-6">
      <Sheet modal={false}>
        <SheetTrigger asChild>
          <Button
            variant="outline"
            size="icon-lg"
            className="relative"
            aria-label={active === 0 ? "Jobs" : `Jobs, ${active} running`}
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
