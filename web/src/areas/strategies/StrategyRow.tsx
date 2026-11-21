import { Link } from "@tanstack/react-router"
import { cn } from "cn"
import { ArrowRight } from "lucide-react"
import type { IndexedStrategy } from "@/api/strategies"
import { IdentityChip } from "@/ui/identity-chip"
import { formatInstant } from "@/ui/instant"
import { KIND_LABELS, latestVersion } from "./strategy-versions"

const COLUMNS =
  "grid grid-cols-[12rem_minmax(0,1fr)_4.5rem_4.5rem_9rem_1rem] items-center gap-x-4 border px-2"

/** The header over the list of strategies, on the rows' own columns (web/DESIGN.md, Patterns,
 * Link rows). */
export function StrategyHead() {
  return (
    <div className={cn(COLUMNS, "h-10 border-transparent border-b-border")}>
      <span data-slot="list-head">Name</span>
      <span data-slot="list-head">Hypothesis</span>
      <span data-slot="list-head">Kind</span>
      <span data-slot="list-head" className="text-right">
        Latest
      </span>
      <span data-slot="list-head" className="text-right">
        Last run
      </span>
    </div>
  )
}

/** A saved strategy as a row that opens its page (web/DESIGN.md, Patterns, Strategies list): its
 * name, and Abandoned where it is marked so; its latest version's hypothesis, cut to two lines,
 * which its page shows whole; its kind; its latest version in its identity chip; and when its
 * newest saved run was made. */
export function StrategyRow({
  strategy,
}: Readonly<{ strategy: IndexedStrategy }>) {
  const latest = latestVersion(strategy)
  return (
    <Link
      to="/strategies/strategy"
      search={{ name: strategy.name, version: latest.version }}
      data-slot="row-link"
      data-testid="strategy-row"
      className={cn(
        COLUMNS,
        "group min-h-10 rounded-xl border-transparent py-2 hover:border-border hover:bg-muted"
      )}
    >
      <span className="flex flex-wrap items-center gap-2">
        <span
          data-testid="strategy-name"
          className="font-medium wrap-anywhere text-foreground group-hover:text-brand"
        >
          {strategy.name}
        </span>
        {strategy.abandoned !== null && (
          <span
            data-testid="abandoned-badge"
            className="rounded-xl bg-accent px-2 py-0.5 text-xs font-semibold text-foreground"
          >
            Abandoned
          </span>
        )}
      </span>
      <span className="line-clamp-2 text-foreground-secondary">
        {latest.hypothesis}
      </span>
      <span className="text-foreground-secondary">
        {KIND_LABELS[strategy.kind]}
      </span>
      <span className="text-right">
        <IdentityChip>{`v${latest.version}`}</IdentityChip>
      </span>
      <span
        data-testid="strategy-last-run"
        className="text-right text-foreground-secondary"
      >
        {strategy.last_run_at === null
          ? "Never run"
          : formatInstant(strategy.last_run_at)}
      </span>
      <ArrowRight
        aria-hidden="true"
        className="size-4 text-foreground-secondary"
      />
    </Link>
  )
}
