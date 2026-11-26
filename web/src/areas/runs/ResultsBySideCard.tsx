import { cn } from "cn"
import type { ResultsBySide } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { Panel } from "@/ui/panel"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import { CLOSED_TRADES_NOTE, noTradeWords } from "./result-words"
import { figureGroups, sideFigure, type Written } from "./side-figures"

/** The table's columns, in order: all trades, then each side. */
const SIDES = [
  { column: "all_trades", heading: "All trades" },
  { column: "long", heading: "Long" },
  { column: "short", heading: "Short" },
] as const

/** The colour of each look of a figure (side-figures.ts). */
const LOOKS: Readonly<Record<Written["look"], string>> = {
  positive: "text-positive",
  negative: "text-negative",
  figure: "text-foreground",
  none: "text-foreground-secondary",
}

/** A run's figures for all its trades, its long trades, and its short trades in one table
 * (web/DESIGN.md, Patterns, Results by side), each figure the API's, money in `currency` and in
 * its sign's colour where it is a profit or a loss (D-117), its rows in five sets set apart; a
 * side the run made no trade on reads None, which the line under the title explains, and the line
 * at the foot says that a side's risk is of its closed trades. */
export function ResultsBySideCard({
  results,
  currency,
}: Readonly<{ results: ResultsBySide; currency: Currency }>) {
  const groups = figureGroups(results.all_trades.funding !== null)
  return (
    <Panel title="By side" description={noTradeWords(results)}>
      <div data-testid="results-by-side" className="-mx-6">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pr-3 pl-6">Figure</TableHead>
              {SIDES.map(({ column, heading }) => (
                <TableHead
                  key={column}
                  className={cn(
                    "text-right",
                    column === "short" ? "w-[12.75rem] pr-6 pl-3" : "w-48 px-3"
                  )}
                >
                  {heading}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          {groups.map((group, at) => (
            <TableBody key={group.id}>
              {at > 0 && <SetApart />}
              {group.rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-testid={`by-side-${row.id}`}
                  className="h-10 hover:bg-muted"
                >
                  <th
                    scope="row"
                    className="py-0 pr-3 pl-6 text-left font-normal whitespace-nowrap text-foreground-secondary"
                  >
                    {row.label}
                  </th>
                  {SIDES.map(({ column }) => (
                    <FigureCell
                      key={column}
                      written={sideFigure(results[column], row, currency)}
                      last={column === "short"}
                    />
                  ))}
                </TableRow>
              ))}
            </TableBody>
          ))}
        </Table>
      </div>
      <p
        data-testid="results-by-side-note"
        className="text-xs text-muted-foreground"
      >
        {CLOSED_TRADES_NOTE}
      </p>
    </Panel>
  )
}

/** The 12 px between two sets of rows: a row of its own, with no hairline, no hover, and nothing
 * a screen reader reads, since a collapsed border between the sets would take its room from the
 * rows beside it (the design review). */
function SetApart() {
  return (
    <tr aria-hidden="true">
      <td colSpan={4} className="h-3 p-0" />
    </tr>
  )
}

function FigureCell({
  written,
  last,
}: Readonly<{ written: Written; last: boolean }>) {
  return (
    <TableCell
      className={cn(
        "py-0 text-right",
        last ? "pr-6 pl-3" : "px-3",
        LOOKS[written.look]
      )}
    >
      {written.text}
    </TableCell>
  )
}
