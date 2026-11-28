import { IdentityChip } from "@/ui/identity-chip"
import { formatInstant } from "@/ui/instant"
import { PercentBar } from "@/ui/percent-bar"
import type { ReproductionState } from "./reproduction-run"

const HASH_DIGITS = 12

/** Where a saved run's reproduction stands, under its status line (web/DESIGN.md, Patterns,
 * Reproduce): in a status region that stands from the start, so that a screen reader hears each
 * change, and that takes no room, its gap to the status line taken back, while nothing was asked
 * for; then on one line of 20 px whatever it says, so that what stands under it moves once, at the
 * press: the job queued, its bar beside its message while it runs, and its verdict with when it
 * came, the trades the saved run's by their hash; other trades, in the negative, the sign of
 * something the run did not pin; or why the run could not be made again, in the server's words. */
export function ReproductionLine({
  state,
}: Readonly<{ state: ReproductionState }>) {
  return (
    <div
      role="status"
      data-testid="reproduction"
      className="flex min-h-5 flex-col justify-center gap-1 empty:-mt-6 empty:min-h-0"
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
      <div className="flex items-center gap-3">
        <span className="w-64 shrink-0">
          <PercentBar
            value={state.job.progress}
            label="Reproduction progress"
          />
        </span>
        <p className="truncate text-xs text-muted-foreground">
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
  const when =
    state.at === null ? "Reproduced" : `Reproduced ${formatInstant(state.at)}`
  if (verdict.verdict === "matched") {
    return (
      <p className="flex flex-wrap items-center gap-2 text-foreground">
        {`${when}: the trades match the saved run's, hash`}
        <IdentityChip testId="reproduction-hash">
          {verdict.trades_hash.slice(0, HASH_DIGITS)}
        </IdentityChip>
      </p>
    )
  }
  if (verdict.verdict === "differed") {
    return (
      <>
        <p className="text-negative">
          {`${when} with other trades: something this run read is not pinned. FEAT kept the reproduction in its cache folder.`}
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
      </>
    )
  }
  return (
    <p className="text-foreground-secondary wrap-anywhere">
      {`Not reproduced: ${verdict.reason}`}
    </p>
  )
}
