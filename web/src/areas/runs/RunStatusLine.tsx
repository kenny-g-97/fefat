import type { SavedRun } from "@/api/runs"
import { IdentityChip } from "@/ui/identity-chip"
import { formatInstant } from "@/ui/instant"
import { StatusBadge } from "@/ui/status-badge"

const KEY_DIGITS = 12

type RunStatusLineProps = Readonly<{
  run: SavedRun
  cached: boolean
  found: string | null
}>

/** Where a saved run stands, in one line over its results (web/DESIGN.md, Patterns, Run page):
 * its badge, Cached where the run opened from a request FEAT had already run, when it was asked
 * for, and its run key; under them, the line `found` holds on how the launch came to this run. */
export function RunStatusLine({ run, cached, found }: RunStatusLineProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <StatusBadge
          status={run.status}
          cancelling={false}
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
        <span className="text-foreground-secondary">
          {`Created ${formatInstant(run.created_at)}`}
        </span>
        <span className="flex items-center gap-2 text-foreground-secondary">
          Run key
          <IdentityChip testId="run-key">
            {run.run_key.slice(0, KEY_DIGITS)}
          </IdentityChip>
        </span>
      </div>
      {found !== null && (
        <p data-testid="run-found" className="text-foreground-secondary">
          {found}
        </p>
      )}
    </div>
  )
}
