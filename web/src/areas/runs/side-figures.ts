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
  moneySign,
} from "@/ui/figures"

const NONE = "None"

/** A figure as its cell writes it, and how it reads: money made or lost in its sign's colour, any
 * other figure in heading text, and None, where nothing is counted, in body text, so that an
 * empty column falls back (web/DESIGN.md, Patterns, Results by side). */
export type Written = Readonly<{
  text: string
  look: "positive" | "negative" | "figure" | "none"
}>

/** A row of the table of a run's figures by side: its name, and how it writes a side's figure in
 * `currency`, or of another table, its own figures. */
export type FigureRow<Figures = SideResults> = Readonly<{
  id: string
  label: string
  written: (figures: Figures, currency: Currency) => Written
}>

/** What a run made and its risk, the figures a side, a run, and buy and hold each have (step
 * 5.23). */
export type ProfitAndRisk = Pick<
  SideResults,
  "net_pnl" | "max_drawdown" | "longest_drawdown_days" | "sharpe"
>

/** A figure where nothing is counted, in body text. */
export const NOTHING: Written = { text: NONE, look: "none" }

function figure(text: string): Written {
  return { text, look: "figure" }
}

/** Money made or lost, as the API's decimal text, in its sign's colour, a zero in heading text. */
function made(text: string, currency: Currency): Written {
  return { text: formatMoney(text, currency), look: signLook(text) }
}

/** An average of money made or lost, a float, in the colour of its sign at the cent. */
function madeOnAverage(value: number | null, currency: Currency): Written {
  if (value === null) {
    return NOTHING
  }
  return {
    text: moneyFigure(value, currency),
    look: signLook(formatFigure(value)),
  }
}

/** How money written as `text` reads: in its sign's colour, a zero, never signed, in heading
 * text. */
function signLook(text: string): Written["look"] {
  const sign = moneySign(text)
  return sign === "zero" ? "figure" : sign
}

/** Money paid or held, as the API's decimal text, in heading text: a cost or a drawdown. */
function paid(text: string, currency: Currency): Written {
  return figure(formatMoney(text, currency))
}

function orNone(value: number | null, write: (value: number) => string) {
  return value === null ? NOTHING : figure(write(value))
}

function ticks(value: number): string {
  return `${formatFigure(value)} ticks`
}

const NET_PNL: FigureRow<ProfitAndRisk> = {
  id: "net-pnl",
  label: "Net P&L",
  written: (side, currency) => made(side.net_pnl, currency),
}

const PROFIT: readonly FigureRow[] = [
  NET_PNL,
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
    written: (side) => figure(formatCount(side.trades)),
  },
  {
    id: "wins",
    label: "Wins",
    written: (side) => figure(formatCount(side.wins)),
  },
  {
    id: "losses",
    label: "Losses",
    written: (side) => figure(formatCount(side.losses)),
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
  label: "Funding received",
  written: (side, currency) =>
    side.funding === null ? NOTHING : made(side.funding, currency),
}

const SLIPPAGE: FigureRow = {
  id: "slippage",
  label: "Slippage",
  written: (side, currency) => paid(side.slippage, currency),
}

const RISK: readonly FigureRow<ProfitAndRisk>[] = [
  {
    id: "max-drawdown",
    label: "Max drawdown",
    written: (side, currency) => paid(side.max_drawdown, currency),
  },
  {
    id: "longest-spell",
    label: "Longest spell under a peak",
    written: (side) => figure(counted(side.longest_drawdown_days, "day")),
  },
  {
    id: "sharpe",
    label: "Sharpe",
    written: (side) => orNone(side.sharpe, formatFigure),
  },
]

/** The rows of a table of what a run made and its risk, as By side writes them: buy and hold's
 * beside the run's (step 5.23). */
export const PROFIT_AND_RISK: readonly FigureRow<ProfitAndRisk>[] = [
  NET_PNL,
  ...RISK,
]

/** A set of the table's rows, set apart from the next. */
export type FigureGroup = Readonly<{ id: string; rows: readonly FigureRow[] }>

/** The table's rows in the five sets a trader reads them in: what the run made, its trades, their
 * averages, what they paid, a perpetual's funding received among it, and their risk. */
export function figureGroups(perpetual: boolean): readonly FigureGroup[] {
  const costs = perpetual ? [FEES, FUNDING, SLIPPAGE] : [FEES, SLIPPAGE]
  return [
    { id: "profit", rows: PROFIT },
    { id: "trades", rows: TRADES },
    { id: "averages", rows: AVERAGES },
    { id: "costs", rows: costs },
    { id: "risk", rows: RISK },
  ]
}

/** `row`'s figure of `side` as its cell writes it, None for a side the run made no trade on. */
export function sideFigure(
  side: SideResults | null,
  row: FigureRow,
  currency: Currency
): Written {
  return side === null ? NOTHING : row.written(side, currency)
}
