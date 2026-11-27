import type { ComparedRun, RunFigures } from "@/api/comparisons"
import type { Currency } from "@/api/runs"
import {
  formatCount,
  formatFigure,
  formatMoney,
  formatShare,
  moneySign,
} from "@/ui/figures"
import { parameterWords } from "./run-words"
import type { Written } from "./side-figures"

const NONE = "None"

/** Each run's mark, in the comparison's order: the colour of its curve (web/DESIGN.md, Palette,
 * and `charts/comparison-option.ts`). */
export const SERIES_MARKS = [
  "bg-brand",
  "bg-chart-2",
  "bg-chart-3",
  "bg-chart-4",
] as const

/** A run of a comparison as its column and its line of the legend name it: its strategy and
 * version, `demo v1`, or No saved version for a strategy built in a notebook. */
export function comparedLabel(run: ComparedRun): string {
  return run.strategy === null
    ? "No saved version"
    : `${run.strategy.name} v${run.strategy.version}`
}

/** What tells a compared run apart from another run of its version: what it trades, its dates,
 * and its parameters, `ES in 5m bars, 2026-03-05 to 2026-03-09, lookback 12, stop_atr 1.5`. */
export function comparedDetail(run: ComparedRun): string {
  const parameters =
    run.strategy === null
      ? ""
      : parameterWords({ parameters: run.strategy.parameters })
  const traded = `${run.instrument} in ${run.timeframe} bars`
  return [traded, `${run.window.start} to ${run.window.end}`, parameters]
    .filter((words) => words !== "")
    .join(", ")
}

/** A change with its sign, as the comparison writes each delta: a plus before a change above
 * zero, none before a zero, a minus as the figure writes it. */
function signedChange(written: string, positive: boolean): string {
  return positive ? `+${written}` : written
}

/** A change of money, as the API's decimal text, in `currency`: `+$921.56`, `-$12.50`, `$0.00`. */
export function moneyChange(text: string, currency: Currency): string {
  return signedChange(
    formatMoney(text, currency),
    moneySign(text) === "positive"
  )
}

/** A change of a count: `+2`, `-1`, `0`. */
export function countChange(change: number): string {
  return signedChange(formatCount(change), change > 0)
}

/** A change of a share, in points of percent at two decimals: `+2.50%`, or a change that rounds
 * to zero, unsigned, `0.00%`. */
export function shareChange(change: number): string {
  const written = formatShare(change)
  return signedChange(written, change > 0 && written !== formatShare(0))
}

/** A change of a ratio the engine works out, at two decimals, or None where either run has none:
 * `+0.31`, `-1.20`. */
export function figureChange(change: number | null): string {
  if (change === null) {
    return NONE
  }
  const written = formatFigure(change)
  return signedChange(written, change > 0 && written !== formatFigure(0))
}

/** A row of the comparison's figures: its name, how it writes a run's figure in `currency`, and
 * how it writes what a run's figure differs by from the reference's. */
export type ComparedRow = Readonly<{
  id: string
  label: string
  figure: (figures: RunFigures, currency: Currency) => Written
  change: (deltas: RunFigures, currency: Currency) => string
}>

function heading(text: string): Written {
  return { text, look: "figure" }
}

function ratio(value: number | null): Written {
  return value === null
    ? { text: NONE, look: "none" }
    : heading(formatFigure(value))
}

function share(value: number | null): Written {
  return value === null
    ? { text: NONE, look: "none" }
    : heading(formatShare(value))
}

/** Net P&L in its sign's colour, a zero in heading text, as every P&L of the app. */
function made(text: string, currency: Currency): Written {
  const sign = moneySign(text)
  return {
    text: formatMoney(text, currency),
    look: sign === "zero" ? "figure" : sign,
  }
}

/** The figures a comparison sets side by side, those of the run page's KPI cards but its fidelity
 * split, each with its change. */
export const COMPARED_ROWS: readonly ComparedRow[] = [
  {
    id: "pnl",
    label: "Net P&L",
    figure: (figures, currency) => made(figures.pnl, currency),
    change: (deltas, currency) => moneyChange(deltas.pnl, currency),
  },
  {
    id: "pnl-share",
    label: "Net P&L of the capital",
    figure: (figures) => share(figures.pnl_share),
    change: (deltas) => shareChange(deltas.pnl_share),
  },
  {
    id: "profit-factor",
    label: "Profit factor",
    figure: (figures) => ratio(figures.profit_factor),
    change: (deltas) => figureChange(deltas.profit_factor),
  },
  {
    id: "expectancy-r",
    label: "Expectancy in R",
    figure: (figures) => ratio(figures.expectancy_r),
    change: (deltas) => figureChange(deltas.expectancy_r),
  },
  {
    id: "win-rate",
    label: "Win rate",
    figure: (figures) => share(figures.win_rate),
    change: (deltas) =>
      deltas.win_rate === null ? NONE : shareChange(deltas.win_rate),
  },
  {
    id: "max-drawdown",
    label: "Max drawdown",
    figure: (figures, currency) =>
      heading(formatMoney(figures.max_drawdown, currency)),
    change: (deltas, currency) => moneyChange(deltas.max_drawdown, currency),
  },
  {
    id: "max-drawdown-share",
    label: "Max drawdown of the capital",
    figure: (figures) => share(figures.max_drawdown_share),
    change: (deltas) => shareChange(deltas.max_drawdown_share),
  },
  {
    id: "sharpe",
    label: "Sharpe",
    figure: (figures) => ratio(figures.sharpe),
    change: (deltas) => figureChange(deltas.sharpe),
  },
  {
    id: "trades",
    label: "Trades",
    figure: (figures) => heading(formatCount(figures.trades)),
    change: (deltas) => countChange(deltas.trades),
  },
]
