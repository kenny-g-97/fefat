import { useDemoJobStart } from "@/api/jobs"
import { Button } from "@/ui/button"
import { Panel } from "@/ui/panel"

/** The demo job (step 4.4), which counts for a minute: the way to watch a job's progress in the
 * top bar's drawer survive a reload and stop on Cancel before real jobs arrive. */
export function DemoJobSection() {
  const start = useDemoJobStart()
  return (
    <Panel
      title="Demo job"
      description="A job that counts for a minute, to follow at the top right and on Home"
    >
      <div className="flex items-center gap-4">
        <Button
          type="button"
          disabled={start.isPending}
          onClick={() => start.mutate()}
        >
          Run demo job
        </Button>
        {start.isSuccess && (
          <p role="status" className="text-foreground-secondary">
            Demo job queued
          </p>
        )}
      </div>
      {start.error !== null && (
        <p role="alert" className="text-negative">
          {start.error.message}
        </p>
      )}
    </Panel>
  )
}
