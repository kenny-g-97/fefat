import { cn } from "cn"
import type { BuyAndHold, RunMetrics } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/ui/table"
import { FigureCell } from "./FigureCell"
import { buyAndHoldNote, lotsWords } from "./market-words"
import { NOTHING, PROFIT_AND_RISK, type ProfitAndRisk } from "./side-figures"

/** A figure column, 12 rem wide as By side's, and the last, widened by the card's edge padding,
 * so that the columns stand still from one run to the next. */
const COLUMN = "w-48 px-3 text-right"
const LAST_COLUMN = "w-[12.75rem] pr-6 pl-3 text-right"
/** A head of the header's lower row, or one spanning both, set on one line 12 px above the
 * header's hairline, as a head centred in its 40 px row stands. */
const LOWER_HEAD = "pb-3 align-bottom"

/** The run beside buy and hold at one lot and at the run's volatility (web/DESIGN.md, Patterns,
 * Market exposure card), each figure the API's, the run's as its metrics hold them, in By side's
 * rows and cells, buy and hold's two columns under one heading; buy and hold at the run's
 * volatility reads None where it has no size, which the line under the table says why of. */
export function BuyAndHoldTable({
  held,
  metrics,
  currency,
}: Readonly<{ held: BuyAndHold; metrics: RunMetrics; currency: Currency }>) {
  const sized = held.kind === "sized" ? held.at_run_volatility : null
  const columns = [
    { column: "run", figures: runFigures(metrics) },
    { column: "one-lot", figures: held.at_one_lot },
    { column: "run-volatility", figures: sized },
  ] as const
  return (
    <div className="flex flex-col gap-3">
      <div data-testid="buy-and-hold" className="-mx-6">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead rowSpan={2} className={cn("pr-3 pl-6", LOWER_HEAD)}>
                Figure
              </TableHead>
              <TableHead rowSpan={2} className={cn(COLUMN, LOWER_HEAD)}>
                This run
              </TableHead>
              <TableHead
                colSpan={2}
                scope="colgroup"
                className="pr-6 pl-3 text-center"
              >
                Buy and hold
              </TableHead>
            </TableRow>
            <TableRow className="hover:bg-transparent">
              <TableHead scope="col" className={cn(COLUMN, LOWER_HEAD)}>
                1 lot
              </TableHead>
              <TableHead scope="col" className={cn(LAST_COLUMN, LOWER_HEAD)}>
                {sized === null ? "Run's volatility" : lotsWords(sized.lots)}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {PROFIT_AND_RISK.map((row) => (
              <TableRow
                key={row.id}
                data-testid={`buy-and-hold-${row.id}`}
                className="h-10 hover:bg-muted"
              >
                <th
                  scope="row"
                  className="py-0 pr-3 pl-6 text-left font-normal whitespace-nowrap text-foreground-secondary"
                >
                  {row.label}
                </th>
                {columns.map(({ column, figures }) => (
                  <FigureCell
                    key={column}
                    written={
                      figures === null
                        ? NOTHING
                        : row.written(figures, currency)
                    }
                    last={column === "run-volatility"}
                  />
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p
        data-testid="buy-and-hold-note"
        className="text-xs text-muted-foreground"
      >
        {buyAndHoldNote(held.kind === "sized" ? null : held.uncounted)}
      </p>
    </div>
  )
}

/** The run's own figures as its metrics hold them, the KPI cards' and the equity chart's. */
function runFigures(metrics: RunMetrics): ProfitAndRisk {
  return {
    net_pnl: metrics.pnl,
    max_drawdown: metrics.drawdown.max_drawdown,
    longest_drawdown_days: metrics.drawdown.longest_drawdown_days,
    sharpe: metrics.daily.sharpe,
  }
}
