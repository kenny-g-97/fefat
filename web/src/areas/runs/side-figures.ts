import type { SideResults } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import {
  counted,
  formatCount,
  formatDuration,
  formatFigure,
  formatMoney,
  formatShare,
  moneyFigure,
} from "@/ui/figures"
import { toneOf } from "./result-words"

const NONE = "None"

/** A figure as its cell writes it, in its sign's colour where it is money made or lost. */
export type Written = Readonly<{
  text: string
  tone: "positive" | "negative" | undefined
}>

/** A row of the table of a run's figures by side: its name, and how it writes a side's figure in
 * `currency`. */
export type FigureRow = Readonly<{
  id: string
  label: string
  written: (side: SideResults, currency: Currency) => Written
}>

function plain(text: string): Written {
  return { text, tone: undefined }
}

/** Money made or lost, as the API's decimal text, in its sign's colour. */
function made(text: string, currency: Currency): Written {
  return { text: formatMoney(text, currency), tone: toneOf(text) }
}

/** An average of money made or lost, a float, in the colour of its sign at the cent. */
function madeOnAverage(value: number | null, currency: Currency): Written {
  if (value === null) {
    return plain(NONE)
  }
  return {
    text: moneyFigure(value, currency),
    tone: toneOf(formatFigure(value)),
  }
}

/** Money paid or held, as the API's decimal text, in no colour: a cost or a drawdown. */
function paid(text: string, currency: Currency): Written {
  return plain(formatMoney(text, currency))
}

function orNone(value: number | null, write: (value: number) => string) {
  return plain(value === null ? NONE : write(value))
}

function ticks(value: number): string {
  return `${formatFigure(value)} ticks`
}

const PROFIT: readonly FigureRow[] = [
  {
    id: "net-pnl",
    label: "Net P&L",
    written: (side, currency) => made(side.net_pnl, currency),
  },
  {
    id: "gross-profit",
    label: "Gross profit",
    written: (side, currency) => made(side.gross_profit, currency),
  },
  {
    id: "gross-loss",
    label: "Gross loss",
    written: (side, currency) => made(side.gross_loss, currency),
  },
  {
    id: "profit-factor",
    label: "Profit factor",
    written: (side) => orNone(side.profit_factor, formatFigure),
  },
]

const TRADES: readonly FigureRow[] = [
  {
    id: "trades",
    label: "Trades",
    written: (side) => plain(formatCount(side.trades)),
  },
  {
    id: "wins",
    label: "Wins",
    written: (side) => plain(formatCount(side.wins)),
  },
  {
    id: "losses",
    label: "Losses",
    written: (side) => plain(formatCount(side.losses)),
  },
  {
    id: "win-rate",
    label: "Win rate",
    written: (side) => orNone(side.win_rate, formatShare),
  },
  {
    id: "trades-per-day",
    label: "Trades a day",
    written: (side) => orNone(side.trades_per_day, formatFigure),
  },
]

const AVERAGES: readonly FigureRow[] = [
  {
    id: "expectancy",
    label: "Expectancy",
    written: (side, currency) => madeOnAverage(side.expectancy, currency),
  },
  {
    id: "expectancy-r",
    label: "Expectancy in R",
    written: (side) => orNone(side.expectancy_r, (r) => `${formatFigure(r)} R`),
  },
  {
    id: "average-win",
    label: "Average win",
    written: (side, currency) => madeOnAverage(side.average_win, currency),
  },
  {
    id: "average-loss",
    label: "Average loss",
    written: (side, currency) => madeOnAverage(side.average_loss, currency),
  },
  {
    id: "win-loss-ratio",
    label: "Average win over loss",
    written: (side) => orNone(side.win_loss_ratio, formatFigure),
  },
  {
    id: "time-in-market",
    label: "Average time in market",
    written: (side) => orNone(side.average_minutes_held, formatDuration),
  },
  {
    id: "average-mae",
    label: "Average MAE",
    written: (side) => orNone(side.average_mae_ticks, ticks),
  },
  {
    id: "average-mfe",
    label: "Average MFE",
    written: (side) => orNone(side.average_mfe_ticks, ticks),
  },
]

const FEES: FigureRow = {
  id: "fees",
  label: "Commissions and fees",
  written: (side, currency) => paid(side.fees, currency),
}

const FUNDING: FigureRow = {
  id: "funding",
  label: "Funding",
  written: (side, currency) =>
    side.funding === null ? plain(NONE) : made(side.funding, currency),
}

const SLIPPAGE: FigureRow = {
  id: "slippage",
  label: "Slippage",
  written: (side, currency) => paid(side.slippage, currency),
}

const RISK: readonly FigureRow[] = [
  {
    id: "max-drawdown",
    label: "Max drawdown",
    written: (side, currency) => paid(side.max_drawdown, currency),
  },
  {
    id: "longest-spell",
    label: "Longest spell under a peak",
    written: (side) => plain(counted(side.longest_drawdown_days, "day")),
  },
  {
    id: "sharpe",
    label: "Sharpe",
    written: (side) => orNone(side.sharpe, formatFigure),
  },
]

/** The table's rows, in the order a trader reads them: what the run made, its trades, their
 * averages, what they paid, a perpetual's funding among it, and their risk. */
export function figureRows(perpetual: boolean): readonly FigureRow[] {
  const costs = perpetual ? [FEES, FUNDING, SLIPPAGE] : [FEES, SLIPPAGE]
  return [...PROFIT, ...TRADES, ...AVERAGES, ...costs, ...RISK]
}

/** `row`'s figure of `side` as its cell writes it, None for a side the run made no trade on. */
export function sideFigure(
  side: SideResults | null,
  row: FigureRow,
  currency: Currency
): Written {
  return side === null ? plain(NONE) : row.written(side, currency)
}
