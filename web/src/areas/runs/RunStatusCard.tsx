import { isActive } from "@/api/jobs"
import { type SubmittedRun, useRunCancellation } from "@/api/runs"
import { Button } from "@/ui/button"
import { Panel } from "@/ui/panel"
import { PercentBar } from "@/ui/percent-bar"
import { StatusBadge } from "@/ui/status-badge"
import { TextLink } from "@/ui/text-link"

type RunStatusCardProps = Readonly<{
  run: SubmittedRun
  found: string | null
}>

/** Where a run without results stands (web/DESIGN.md, Patterns, Run page): its badge and the line
 * `found` holds on how the launch came to this run; then while its job is under way its bar, its
 * last message, and Cancel, and once it ended without a run, why, with the way back to its
 * version. */
export function RunStatusCard({ run, found }: RunStatusCardProps) {
  const cancelling =
    run.status === "running" && run.cancel_requested_at !== null
  return (
    <Panel title="Status">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge
          status={run.status}
          cancelling={cancelling}
          testId="run-page-status"
        />
      </div>
      {found !== null && (
        <p data-testid="run-found" className="text-foreground-secondary">
          {found}
        </p>
      )}
      <SubmittedState run={run} />
    </Panel>
  )
}

function SubmittedState({ run }: Readonly<{ run: SubmittedRun }>) {
  if (isActive(run)) {
    return <UnderWay run={run} />
  }
  return (
    <div className="flex flex-col items-start gap-3">
      {run.error !== null && (
        <p
          role="alert"
          data-testid="run-error"
          className="whitespace-pre-wrap text-negative wrap-anywhere"
        >
          {run.error}
        </p>
      )}
      <TextLink
        to="/strategies/strategy"
        search={{ name: run.strategy.name, version: run.strategy.version }}
      >
        Back to its version
      </TextLink>
    </div>
  )
}

function UnderWay({ run }: Readonly<{ run: SubmittedRun }>) {
  const cancellation = useRunCancellation()
  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-8 items-center gap-3">
        <PercentBar value={run.progress} label="Backtest progress" />
        <Button
          variant="ghost"
          size="sm"
          data-testid="run-page-cancel"
          disabled={cancellation.isPending || run.cancel_requested_at !== null}
          onClick={() => cancellation.mutate(run.id)}
        >
          Cancel
        </Button>
      </div>
      <p data-testid="run-message" className="text-xs text-muted-foreground">
        {run.status === "queued"
          ? "Queued until a worker is free"
          : run.message}
      </p>
      {cancellation.error !== null && (
        <p role="alert" className="text-negative">
          {cancellation.error.message}
        </p>
      )}
    </div>
  )
}
