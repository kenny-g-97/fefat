import { cn } from "cn"
import type {
  BuyAndHold,
  BuyAndHoldFigures,
  RunMetrics,
} from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { counted, formatFigure, formatMoney } from "@/ui/figures"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import { buyAndHoldLabel, buyAndHoldNote } from "./market-words"
import { toneOf } from "./result-words"

/** What a column of the table holds: a run's figures or buy and hold's, as the API gives them. */
type Figures = Omit<BuyAndHoldFigures, "lots">

/** A figure as a cell writes it, in its sign's colour where it is money made or lost. */
type Written = Readonly<{ text: string; tone?: "positive" | "negative" }>

const ROWS: readonly Readonly<{
  id: string
  label: string
  written: (figures: Figures, currency: Currency) => Written
}>[] = [
  {
    id: "net-pnl",
    label: "Net P&L",
    written: (figures, currency) => ({
      text: formatMoney(figures.net_pnl, currency),
      tone: toneOf(figures.net_pnl),
    }),
  },
  {
    id: "max-drawdown",
    label: "Max drawdown",
    written: (figures, currency) => ({
      text: formatMoney(figures.max_drawdown, currency),
    }),
  },
  {
    id: "longest-spell",
    label: "Longest spell under a peak",
    written: (figures) => ({
      text: counted(figures.longest_drawdown_days, "day"),
    }),
  },
  {
    id: "sharpe",
    label: "Sharpe",
    written: (figures) => ({
      text: figures.sharpe === null ? "None" : formatFigure(figures.sharpe),
    }),
  },
]

const LOOKS = {
  positive: "text-positive",
  negative: "text-negative",
} as const

/** The run beside buy and hold at one lot and at the run's volatility (web/DESIGN.md, Patterns,
 * Market exposure card), each figure the API's, the run's as its metrics hold them; buy and hold
 * at the run's volatility reads None where it has no size, which the line under the table says
 * why of. */
export function BuyAndHoldTable({
  held,
  metrics,
  currency,
}: Readonly<{ held: BuyAndHold; metrics: RunMetrics; currency: Currency }>) {
  const sized = held.at_run_volatility
  const columns = [
    { heading: "This run", figures: runFigures(metrics) },
    { heading: "Buy and hold, 1 lot", figures: held.at_one_lot },
    {
      heading:
        sized === null
          ? "Buy and hold at the run's volatility"
          : buyAndHoldLabel(sized.lots),
      figures: sized,
    },
  ]
  return (
    <div className="flex flex-col gap-3">
      <div data-testid="buy-and-hold" className="-mx-6">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pr-3 pl-6">Figure</TableHead>
              {columns.map(({ heading }, at) => (
                <TableHead
                  key={heading}
                  className={cn(
                    "text-right whitespace-normal",
                    at === columns.length - 1
                      ? "w-[14.75rem] pr-6 pl-3"
                      : "w-56 px-3"
                  )}
                >
                  {heading}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {ROWS.map((row) => (
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
                {columns.map(({ heading, figures }, at) => (
                  <FigureCell
                    key={heading}
                    written={
                      figures === null ? null : row.written(figures, currency)
                    }
                    last={at === columns.length - 1}
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
        {buyAndHoldNote(held.uncounted)}
      </p>
    </div>
  )
}

/** The run's own figures as its metrics hold them, the KPI cards' and the equity chart's. */
function runFigures(metrics: RunMetrics): Figures {
  return {
    net_pnl: metrics.pnl,
    max_drawdown: metrics.drawdown.max_drawdown,
    longest_drawdown_days: metrics.drawdown.longest_drawdown_days,
    sharpe: metrics.daily.sharpe,
  }
}

function FigureCell({
  written,
  last,
}: Readonly<{ written: Written | null; last: boolean }>) {
  return (
    <TableCell
      className={cn(
        "py-0 text-right",
        last ? "pr-6 pl-3" : "px-3",
        written === null && "text-foreground-secondary",
        written !== null &&
          (written.tone === undefined ? "text-foreground" : LOOKS[written.tone])
      )}
    >
      {written === null ? "None" : written.text}
    </TableCell>
  )
}
