import { isActive } from "@/api/jobs"
import {
  type ListedRun,
  type SubmittedRun,
  useRunCancellation,
} from "@/api/runs"
import { Button } from "@/ui/button"
import { IdentityChip } from "@/ui/identity-chip"
import { formatInstant } from "@/ui/instant"
import { Panel } from "@/ui/panel"
import { PercentBar } from "@/ui/percent-bar"
import { StatusBadge } from "@/ui/status-badge"
import { TextLink } from "@/ui/text-link"

const KEY_DIGITS = 12

type RunStatusCardProps = Readonly<{ run: ListedRun; cached: boolean }>

/** Where a run stands (web/DESIGN.md, Patterns, Run page): its badge, then while its job is under
 * way its bar, its last message, and Cancel; once it ended without a run, why, with the way back
 * to its version; once saved, when, its run key, and Cached where the run opened from a request
 * FEAT had already run. */
export function RunStatusCard({ run, cached }: RunStatusCardProps) {
  const cancelling =
    run.state === "submitted" &&
    run.status === "running" &&
    run.cancel_requested_at !== null
  return (
    <Panel title="Status">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge
          status={run.status}
          cancelling={cancelling}
          testId="run-page-status"
        />
        {cached && (
          <span
            data-testid="run-cached"
            className="rounded-xl border border-transparent bg-accent px-2 py-0.5 text-xs font-semibold text-foreground"
          >
            Cached
          </span>
        )}
      </div>
      {run.state === "saved" ? (
        <div className="flex flex-col gap-2">
          {cached && (
            <p className="text-foreground-secondary">
              FEAT found this run saved and ran nothing.
            </p>
          )}
          <p className="text-foreground-secondary">
            {`Saved ${formatInstant(run.created_at)}`}
          </p>
          <p className="flex items-center gap-2 text-foreground-secondary">
            Run key
            <IdentityChip testId="run-key">
              {run.run_key.slice(0, KEY_DIGITS)}
            </IdentityChip>
          </p>
          <p className="text-foreground-secondary">
            Its metrics, equity curve, and trades will appear here
          </p>
        </div>
      ) : (
        <SubmittedState run={run} />
      )}
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
