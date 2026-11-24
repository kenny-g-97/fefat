import { Link } from "@tanstack/react-router"
import { cn } from "cn"
import { ArrowRight } from "lucide-react"
import { isActive } from "@/api/jobs"
import {
  type ListedRun,
  runAddress,
  type SavedRun,
  type SubmittedRun,
  useRunCancellation,
} from "@/api/runs"
import { Button } from "@/ui/button"
import { formatCount, formatMoney, moneySign } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { PercentBar } from "@/ui/percent-bar"
import { StatusBadge } from "@/ui/status-badge"
import type { RunsSearch } from "./run-search"
import { runDetail, slippageWords } from "./run-words"

// shortcut: fixed tracks fit a window of 1280 px beside the sidebar, the strategy taking what is
// left and a long name wrapping, the money's 7 rem a loss of -$123,456.78 or -2,721.56 USDT
// (D-117); content-sized tracks through subgrid if a column outgrows them.
const COLUMNS =
  "grid grid-cols-[minmax(0,1fr)_5.5rem_5.5rem_5rem_6rem_7rem_3.5rem_7rem_4.5rem] items-center gap-x-3 gap-y-1 border px-2"
const FIGURE = "text-right text-foreground-secondary"

/** The header over the runs, on the rows' own columns (web/DESIGN.md, Patterns, Runs list). */
export function RunHead() {
  return (
    <div
      data-testid="run-head"
      className={cn(COLUMNS, "h-10 border-transparent border-b-border")}
    >
      <span data-slot="list-head">Strategy</span>
      <span data-slot="list-head" className="text-right">
        From
      </span>
      <span data-slot="list-head" className="text-right">
        To
      </span>
      <span data-slot="list-head" className="text-right">
        Slippage
      </span>
      <span data-slot="list-head">Status</span>
      <span data-slot="list-head" className="text-right">
        Net P&amp;L
      </span>
      <span data-slot="list-head" className="text-right">
        Trades
      </span>
      <span data-slot="list-head" className="text-right">
        Max DD
      </span>
    </div>
  )
}

/** A run as a row that opens its page (web/DESIGN.md, Patterns, Runs list): what it ran, its
 * dates and slippage, its status, then how it went once saved, or its bar while it runs, what it
 * trades and its parameters on a line under them, with Cancel beside the row's link, since no
 * button sits inside one, and why where a Cancel was refused. The page is told the list's
 * `filters`, which its Back to Runs returns to. */
export function RunRow({
  run,
  filters,
}: Readonly<{ run: ListedRun; filters: RunsSearch }>) {
  const cancellation = useRunCancellation()
  return (
    <li>
      <div className="relative">
        <RunLink run={run} filters={filters} />
        {run.state === "submitted" && isActive(run) && (
          <span className="absolute top-1 right-2">
            <Button
              variant="ghost"
              size="sm"
              data-testid="run-cancel"
              aria-label={`Cancel the run of ${run.strategy.name}`}
              disabled={
                cancellation.isPending || run.cancel_requested_at !== null
              }
              onClick={() => cancellation.mutate(run.id)}
            >
              Cancel
            </Button>
          </span>
        )}
      </div>
      {isActive(run) && cancellation.error !== null && (
        <p
          role="alert"
          data-testid="run-cancel-refusal"
          className="px-2 pt-1 text-xs text-negative wrap-anywhere"
        >
          {cancellation.error.message}
        </p>
      )}
    </li>
  )
}

function RunLink({
  run,
  filters,
}: Readonly<{ run: ListedRun; filters: RunsSearch }>) {
  const detail = runDetail(run)
  return (
    <Link
      to="/runs/run"
      search={runAddress(run)}
      state={{ runsFilters: filters }}
      data-slot="row-link"
      data-testid="run-row"
      className={cn(
        COLUMNS,
        "group min-h-10 rounded-xl border-transparent py-2 hover:border-border hover:bg-muted"
      )}
    >
      <span className="flex min-w-0 flex-wrap items-center gap-2">
        {run.strategy === null ? (
          <span className="text-foreground-secondary">No saved version</span>
        ) : (
          <>
            <span
              data-testid="run-strategy"
              className="font-medium wrap-anywhere text-foreground group-hover:text-brand"
            >
              {run.strategy.name}
            </span>
            <IdentityChip>{`v${run.strategy.version}`}</IdentityChip>
          </>
        )}
      </span>
      <span className={FIGURE}>{run.start}</span>
      <span className={FIGURE}>
        <span className="sr-only">to </span>
        {run.end}
      </span>
      <span data-testid="run-slippage" className={FIGURE}>
        {slippageWords(run)}
      </span>
      <span>
        <StatusBadge
          status={run.status}
          cancelling={
            run.state === "submitted" &&
            run.status === "running" &&
            run.cancel_requested_at !== null
          }
          testId="run-status"
        />
      </span>
      {run.state === "saved" ? (
        <SavedFigures run={run} />
      ) : (
        <SubmittedFigures run={run} />
      )}
      {!isActive(run) && (
        <ArrowRight
          aria-hidden="true"
          data-testid="run-arrow"
          className="size-4 justify-self-end text-foreground-secondary"
        />
      )}
      {detail !== "" && (
        <span
          data-testid="run-parameters"
          title={detail}
          className="col-span-full truncate text-xs text-muted-foreground"
        >
          {detail}
        </span>
      )}
    </Link>
  )
}

function SavedFigures({ run }: Readonly<{ run: SavedRun }>) {
  const { pnl, trades, max_drawdown: drawdown } = run.key_metrics
  const sign = moneySign(pnl)
  return (
    <>
      <span
        data-testid="run-pnl"
        className={cn(
          "text-right font-semibold",
          sign === "positive" && "text-positive",
          sign === "negative" && "text-negative",
          sign === "zero" && "text-foreground"
        )}
      >
        {formatMoney(pnl, run.currency)}
      </span>
      <span data-testid="run-trades" className={FIGURE}>
        {formatCount(trades)}
      </span>
      <span data-testid="run-drawdown" className={FIGURE}>
        {formatMoney(drawdown, run.currency)}
      </span>
    </>
  )
}

/** A submission's three columns: its bar while its job is under way, else why it ended. */
function SubmittedFigures({ run }: Readonly<{ run: SubmittedRun }>) {
  if (isActive(run)) {
    return (
      <span className="col-span-3 flex min-w-0 items-center">
        <PercentBar value={run.progress} label="Backtest progress" />
      </span>
    )
  }
  return (
    <span
      className="col-span-3 truncate text-xs text-negative"
      title={run.error === null ? undefined : run.error}
    >
      {run.error}
    </span>
  )
}
