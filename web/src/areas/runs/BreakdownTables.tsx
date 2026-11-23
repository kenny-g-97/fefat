import { cn } from "cn"
import type { Outcome, RunMetrics } from "@/api/run-results"
import {
  fidelityLabel,
  formatCount,
  formatMoney,
  moneySign,
  sentenceCase,
} from "@/ui/figures"
import { Panel } from "@/ui/panel"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import { hourLabel } from "./result-words"

type BreakdownTableProps = Readonly<{
  id: string
  title: string
  column: string
  groups: Readonly<Record<string, Outcome>>
  name: (key: string) => string
}>

/** The run's trades by exit reason, entry hour in the exchange's time zone, weekday, year, and
 * fidelity (web/DESIGN.md, Patterns, Breakdown tables), the hours, the longest, in a column of
 * their own beside the others; one sentence stands in for them where the run has no trade. */
export function BreakdownTables({
  breakdowns,
}: Readonly<{ breakdowns: RunMetrics["breakdowns"] }>) {
  if (Object.keys(breakdowns.exit_reason).length === 0) {
    return (
      <Panel title="Breakdowns">
        <p data-testid="breakdowns-empty" className="text-foreground-secondary">
          This run made no trade, so there is nothing to break down.
        </p>
      </Panel>
    )
  }
  return (
    <div className="grid grid-cols-2 items-start gap-6">
      <div className="flex flex-col gap-6">
        <BreakdownTable
          id="exit_reason"
          title="By exit reason"
          column="Exit"
          groups={breakdowns.exit_reason}
          name={sentenceCase}
        />
        <BreakdownTable
          id="weekday"
          title="By weekday"
          column="Day"
          groups={breakdowns.weekday}
          name={sentenceCase}
        />
        <BreakdownTable
          id="year"
          title="By year"
          column="Year"
          groups={breakdowns.year}
          name={(year) => year}
        />
        <BreakdownTable
          id="fidelity"
          title="By fidelity"
          column="Entry on"
          groups={breakdowns.fidelity}
          name={fidelityLabel}
        />
      </div>
      <BreakdownTable
        id="hour"
        title="By hour of entry, exchange time"
        column="Hour"
        groups={breakdowns.hour}
        name={hourLabel}
      />
    </div>
  )
}

function BreakdownTable({
  id,
  title,
  column,
  groups,
  name,
}: BreakdownTableProps) {
  return (
    <Panel title={title}>
      <div data-testid={`breakdown-${id}`} className="-mx-6 -mb-2">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pr-3 pl-6">{column}</TableHead>
              <TableHead className="px-3 text-right">Trades</TableHead>
              <TableHead className="px-3 text-right">Wins</TableHead>
              <TableHead className="pr-6 pl-3 text-right">Net P&L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.entries(groups).map(([key, group]) => (
              <TableRow
                key={key}
                data-testid="breakdown-row"
                className="h-10 hover:bg-muted"
              >
                <TableCell className="py-0 pr-3 pl-6 font-medium text-foreground">
                  {name(key)}
                </TableCell>
                <TableCell className="px-3 py-0 text-right text-foreground-secondary">
                  {formatCount(group.trades)}
                </TableCell>
                <TableCell className="px-3 py-0 text-right text-foreground-secondary">
                  {formatCount(group.wins)}
                </TableCell>
                <TableCell
                  className={cn(
                    "py-0 pr-6 pl-3 text-right font-semibold text-foreground",
                    moneySign(group.pnl) === "positive" && "text-positive",
                    moneySign(group.pnl) === "negative" && "text-negative"
                  )}
                >
                  {formatMoney(group.pnl)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Panel>
  )
}
