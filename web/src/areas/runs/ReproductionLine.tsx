import { IdentityChip } from "@/ui/identity-chip"
import { PercentBar } from "@/ui/percent-bar"
import type { ReproductionState } from "./reproduction-run"

const HASH_DIGITS = 12

/** Where a saved run's reproduction stands, under its status line (web/DESIGN.md, Patterns,
 * Reproduce): in a status region that stands from the start, so that a screen reader hears each
 * change, the job queued, its bar while it runs, and its verdict: the trades the saved run's,
 * by their hash; other trades, in the negative, the sign of something the run did not pin; or why
 * the run could not be made again, in the server's words. */
export function ReproductionLine({
  state,
}: Readonly<{ state: ReproductionState }>) {
  return (
    <div
      role="status"
      data-testid="reproduction"
      className="flex flex-col gap-2"
    >
      <ReproductionWords state={state} />
    </div>
  )
}

function ReproductionWords({ state }: Readonly<{ state: ReproductionState }>) {
  if (state.kind === "idle") {
    return null
  }
  if (state.kind === "starting") {
    return (
      <p className="text-xs text-muted-foreground">Queueing the reproduction</p>
    )
  }
  if (state.kind === "running") {
    return (
      <div className="flex max-w-lg flex-col gap-1">
        <PercentBar value={state.job.progress} label="Reproduction progress" />
        <p className="text-xs text-muted-foreground">
          {state.job.message === null
            ? "Reproducing the run"
            : state.job.message}
        </p>
      </div>
    )
  }
  if (state.kind === "failed") {
    return <p className="text-negative wrap-anywhere">{state.message}</p>
  }
  const verdict = state.reproduction
  if (verdict.verdict === "matched") {
    return (
      <p className="flex flex-wrap items-center gap-2 text-foreground">
        Reproduced: the trades match the saved run's, hash
        <IdentityChip testId="reproduction-hash">
          {verdict.trades_hash.slice(0, HASH_DIGITS)}
        </IdentityChip>
      </p>
    )
  }
  if (verdict.verdict === "differed") {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-negative">
          Reproduced with other trades: something this run read is not pinned.
          FEAT kept the reproduction in its cache folder.
        </p>
        <p className="flex flex-wrap items-center gap-2 text-foreground-secondary">
          Saved
          <IdentityChip>
            {verdict.saved_trades_hash.slice(0, HASH_DIGITS)}
          </IdentityChip>
          Reproduced
          <IdentityChip>
            {verdict.reproduced_trades_hash.slice(0, HASH_DIGITS)}
          </IdentityChip>
        </p>
      </div>
    )
  }
  return (
    <p className="text-foreground-secondary wrap-anywhere">
      {`Not reproduced: ${verdict.reason}`}
    </p>
  )
}
