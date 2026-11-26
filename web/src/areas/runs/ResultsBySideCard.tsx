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
import { sidesNote } from "./result-words"
import { figureRows, sideFigure, type Written } from "./side-figures"

/** The table's columns, in order: all trades, then each side. */
const SIDES = [
  { column: "all_trades", heading: "All trades" },
  { column: "long", heading: "Long" },
  { column: "short", heading: "Short" },
] as const

/** A run's figures for all its trades, its long trades, and its short trades in one table
 * (web/DESIGN.md, Patterns, Results by side), each figure the API's, money in `currency` and in
 * its sign's colour where it is a profit or a loss (D-117); a side the run made no trade on reads
 * None, and the line under the table says why, and that a side's risk is of its closed trades. */
export function ResultsBySideCard({
  results,
  currency,
}: Readonly<{ results: ResultsBySide; currency: Currency }>) {
  const rows = figureRows(results.all_trades.funding !== null)
  return (
    <Panel title="By side">
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
                    column === "short" ? "pr-6 pl-3" : "px-3"
                  )}
                >
                  {heading}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.id}
                data-testid={`by-side-${row.id}`}
                className="h-10 hover:bg-muted"
              >
                <th
                  scope="row"
                  className="py-0 pr-3 pl-6 text-left font-medium whitespace-nowrap text-foreground"
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
        </Table>
      </div>
      <p
        data-testid="results-by-side-note"
        className="text-xs text-muted-foreground"
      >
        {sidesNote(results)}
      </p>
    </Panel>
  )
}

function FigureCell({
  written,
  last,
}: Readonly<{ written: Written; last: boolean }>) {
  return (
    <TableCell
      className={cn(
        "py-0 text-right text-foreground-secondary",
        last ? "pr-6 pl-3" : "px-3",
        written.tone === "positive" && "text-positive",
        written.tone === "negative" && "text-negative"
      )}
    >
      {written.text}
    </TableCell>
  )
}
