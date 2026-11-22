import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { cn } from "cn"
import { isActive, jobsQuery } from "@/api/jobs"
import {
  type ListedRun,
  liveRun,
  recentRunsQuery,
  runAddress,
  VERDICT_LABELS,
} from "@/api/runs"
import { formatMoney, moneySign } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { Panel } from "@/ui/panel"
import { QueryBody } from "@/ui/query-body"
import { StatusBadge } from "@/ui/status-badge"
import { TextLink } from "@/ui/text-link"

/** Home's latest backtests (web/DESIGN.md, Patterns, Recent runs card), a row each that opens the
 * run: what it ran, then its robustness verdict and net P&L once saved, or its status and percent
 * while it runs. A list it cannot load fails here alone. */
export function RecentRunsWidget() {
  const runs = useQuery(recentRunsQuery)
  const jobs = useQuery(jobsQuery)
  return (
    <Panel
      title="Recent runs"
      action={<TextLink to="/runs">All runs</TextLink>}
    >
      <QueryBody query={runs}>
        {(page) =>
          page.runs.length === 0 ? (
            <p className="flex min-h-24 items-center text-foreground-secondary">
              No backtests yet. Open a strategy and press Run backtest.
            </p>
          ) : (
            <ul className="-mx-2 flex flex-col gap-1">
              {page.runs.map((run) => (
                <RecentRun key={run.id} run={liveRun(run, jobs.data)} />
              ))}
            </ul>
          )
        }
      </QueryBody>
    </Panel>
  )
}

function RecentRun({ run }: Readonly<{ run: ListedRun }>) {
  return (
    <li>
      <Link
        to="/runs/run"
        search={runAddress(run)}
        data-slot="row-link"
        data-testid="recent-run"
        className="group grid min-h-10 grid-cols-[minmax(0,1fr)_auto_6rem] items-center gap-x-3 rounded-xl border border-transparent p-2 hover:border-border hover:bg-muted"
      >
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          {run.strategy === null ? (
            <span className="text-foreground-secondary">No saved version</span>
          ) : (
            <>
              <span className="font-medium wrap-anywhere text-foreground group-hover:text-brand">
                {run.strategy.name}
              </span>
              <IdentityChip>{`v${run.strategy.version}`}</IdentityChip>
            </>
          )}
        </span>
        <RecentState run={run} />
      </Link>
    </li>
  )
}

function RecentState({ run }: Readonly<{ run: ListedRun }>) {
  if (run.state === "submitted") {
    return (
      <>
        <StatusBadge
          status={run.status}
          cancelling={
            run.status === "running" && run.cancel_requested_at !== null
          }
        />
        <span className="text-right font-semibold text-foreground">
          {isActive(run) ? `${Math.round(run.progress)}%` : ""}
        </span>
      </>
    )
  }
  const { pnl, verdict } = run.key_metrics
  const sign = moneySign(pnl)
  return (
    <>
      <span
        data-testid="recent-verdict"
        className="rounded-xl border border-transparent bg-accent px-2 py-0.5 text-xs font-semibold text-foreground"
      >
        {VERDICT_LABELS[verdict]}
      </span>
      <span
        data-testid="recent-pnl"
        className={cn(
          "text-right font-semibold",
          sign === "positive" && "text-positive",
          sign === "negative" && "text-negative",
          sign === "zero" && "text-foreground"
        )}
      >
        {formatMoney(pnl)}
      </span>
    </>
  )
}
