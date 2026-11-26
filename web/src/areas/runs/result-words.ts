import type {
  MonteCarlo,
  PathFigure,
  ResultsBySide,
  SampleSize,
} from "@/api/run-results"
import type { Currency } from "@/api/runs"
import { counted, formatFigure, moneyFigure, moneySign } from "@/ui/figures"

const SAMPLE_SIZES: Readonly<Record<SampleSize, string>> = {
  below_minimum: "under the 30 a sample needs at the least",
  minimum: "past the minimum of 30, under the 100 preferred",
  preferred: "past the 100 preferred, under the 200 of high confidence",
  high_confidence: "past the 200 of high confidence",
}

/** An hour of a breakdown, as its key gives it, in the exchange's time zone: `9` is `09:00`. */
export function hourLabel(hour: string): string {
  return `${hour.padStart(2, "0")}:00`
}

/** A run's trades against the counts a sample needs: `24 trades, under the 30 ...`. */
export function sampleSizeWords(size: SampleSize, trades: number): string {
  return `${counted(trades, "trade")}, ${SAMPLE_SIZES[size]}`
}

/** A change between two runs of the fidelity check, as the API writes it, with its sign: a figure
 * above zero takes a plus, since the column compares. */
export function signed(
  written: string,
  sign: "positive" | "negative" | "zero"
) {
  return sign === "positive" ? `+${written}` : written
}

/** The tone of money as the API writes it: its sign's colour, none for zero. */
export function toneOf(money: string): "positive" | "negative" | undefined {
  const sign = moneySign(money)
  return sign === "zero" ? undefined : sign
}

/** A figure the engine worked out, at two decimals, or None where it could count nothing. */
export function figureOrNone(value: number | null): string {
  return value === null ? "None" : formatFigure(value)
}

/** What a Monte Carlo drew, and what its paths cannot show: `1,000 paths of 24 trades, drawn with
 * replacement from seed 0.`, then that its drawdowns are of closed trades and that a path keeps no
 * streak across days. */
export function monteCarloNote({
  paths,
  trades,
  seed,
}: Pick<MonteCarlo, "paths" | "trades" | "seed">): string {
  return `${counted(paths, "path")} of ${counted(trades, "trade")}, drawn with replacement from seed ${seed}. Drawdowns are of closed trades, and a path keeps no streak across days.`
}

/** What the table of a run's figures by side says under it (step 5.22): that a side's risk is of
 * its closed trades, as all trades' is not. */
export const CLOSED_TRADES_NOTE =
  "A side's max drawdown, longest spell under a peak, and Sharpe are of its closed trades, walked from the capital in the order they closed; those of all trades mark open trades to market."

/** What the table says under its title of a side the run made no trade on, whose column reads
 * None, so that the reason stands beside the column; none where both sides traded. */
export function noTradeWords({
  long,
  short,
}: Pick<ResultsBySide, "long" | "short">): string | undefined {
  if (long === null && short === null) {
    return "This run made no trade, so the Long and Short columns read None."
  }
  if (long === null || short === null) {
    const side = long === null ? "long" : "short"
    const column = long === null ? "Long" : "Short"
    return `This run made no ${side} trade, so the ${column} column reads None.`
  }
  return undefined
}

/** A chart the Monte Carlo card offers: the paths' equity fan, or one of their figures against the
 * percent of them (step 5.21). */
export type MonteCarloChart = "equity" | PathFigure

/** The Monte Carlo card's charts as its select offers them, in the prompt's order. */
export const MONTE_CARLO_CHARTS: readonly Readonly<{
  value: MonteCarloChart
  label: string
}>[] = [
  { value: "equity", label: "Equity" },
  { value: "net_pnl", label: "Net P&L" },
  { value: "max_drawdown", label: "Max drawdown" },
  { value: "profit_factor", label: "Profit factor" },
  { value: "average_mae_ticks", label: "Avg. MAE" },
  { value: "average_mfe_ticks", label: "Avg. MFE" },
]

/** Each figure of the paths: its name in a sentence, and what it counts in. */
export const PATH_FIGURES: Readonly<
  Record<
    PathFigure,
    Readonly<{ inWords: string; unit: "money" | "ticks" | "ratio" }>
  >
> = {
  net_pnl: { inWords: "net P&L", unit: "money" },
  max_drawdown: { inWords: "max drawdown", unit: "money" },
  profit_factor: { inWords: "profit factor", unit: "ratio" },
  average_mae_ticks: { inWords: "average MAE", unit: "ticks" },
  average_mfe_ticks: { inWords: "average MFE", unit: "ticks" },
}

/** What a run without a losing trade says in place of its own profit factor. */
export const NO_OWN_PROFIT_FACTOR =
  "This run had no losing trade, so it has no profit factor"

/** What a figure's chart says in its place where no path drew a losing trade. */
export const NO_PATH_PROFIT_FACTOR =
  "No path drew a losing trade, so none has a profit factor."

/** The tone of a figure of the paths: the net P&L in the colour of its sign as the page writes it,
 * at the cent, as every net P&L on the page stands, so that an amount written as zero, its minus
 * dropped, takes none; none for a path without the figure, and for every other figure. */
export function pathFigureTone(
  figure: PathFigure,
  value: number | null
): "positive" | "negative" | undefined {
  if (figure !== "net_pnl" || value === null) {
    return undefined
  }
  return toneOf(formatFigure(value))
}

/** A figure of the paths as the page writes it: money in `currency` (D-117), a profit factor at
 * two decimals as the KPI cards write it, ticks at two decimals with their unit, `12.35 ticks`,
 * and None where a path has none. */
export function pathFigureWritten(
  figure: PathFigure,
  value: number | null,
  currency: Currency
): string {
  if (value === null) {
    return "None"
  }
  const { unit } = PATH_FIGURES[figure]
  if (unit === "money") {
    return moneyFigure(value, currency)
  }
  return unit === "ticks" ? `${formatFigure(value)} ticks` : formatFigure(value)
}

/** Where the paths stand at `percent` of them: `95% of paths at or under this max drawdown`, or,
 * where the path there has no profit factor, why. */
export function percentWords(
  figure: PathFigure,
  percent: number,
  value: number | null
): string {
  return value === null
    ? `The path at ${percent}% drew no losing trade, so it has no profit factor`
    : `${percent}% of paths at or under this ${PATH_FIGURES[figure].inWords}`
}
