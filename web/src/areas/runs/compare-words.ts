import type { ComparedRun, RunFigures } from "@/api/comparisons"
import type { Currency } from "@/api/runs"
import {
  fidelityInASentence,
  formatCount,
  formatFigure,
  formatMoney,
  formatShare,
  moneySign,
} from "@/ui/figures"
import { parameterText, slippageSaid } from "./run-words"
import { figure, made, orNone, type Written } from "./side-figures"

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

/** A part of what a compared run is, named by `key` so that the same part of another run is
 * found; a setting is said only where the runs differ by it. */
type DetailPart = Readonly<{ key: string; words: string; setting: boolean }>

function detailParts(run: ComparedRun): readonly DetailPart[] {
  const { config } = run
  const parameters =
    run.strategy === null ? [] : Object.entries(run.strategy.parameters)
  const contract =
    config.contract === null || config.contract === undefined
      ? "spliced"
      : config.contract
  return [
    {
      key: "traded",
      words: `${run.instrument} in ${run.timeframe} bars`,
      setting: false,
    },
    {
      key: "dates",
      words: `${run.window.start} to ${run.window.end}`,
      setting: false,
    },
    ...parameters.map(([name, value]) => ({
      key: `parameter ${name}`,
      words: `${name} ${parameterText(value)}`,
      setting: false,
    })),
    {
      key: "slippage",
      words: slippageSaid(config.slippage_ticks),
      setting: true,
    },
    {
      key: "fidelity",
      words: `filled on ${fidelityInASentence(config.fidelity)}`,
      setting: true,
    },
    { key: "fees", words: `${config.fee_table} fees`, setting: true },
    {
      key: "capital",
      words: `${formatMoney(config.capital, run.currency)} of capital`,
      setting: true,
    },
    { key: "contract", words: contract, setting: true },
    {
      key: "latency",
      words: `${config.latency_ms} ms of latency`,
      setting: true,
    },
  ]
}

/** What tells each of `runs` apart, as the comparison's legend says it (web/DESIGN.md, Patterns,
 * Comparison chart): first the parts in which the runs differ, settings such as a stress's
 * slippage among them, in their order, then what each trades, its dates, and its parameters, a
 * setting all of them share left out, so that an ellipsis never cuts what differs. */
export function comparedDetails(
  runs: readonly ComparedRun[]
): readonly string[] {
  const parts = runs.map(detailParts)
  const differs = (part: DetailPart) =>
    parts.some(
      (other) =>
        other.find((each) => each.key === part.key)?.words !== part.words
    )
  return parts.map((own) =>
    [
      ...own.filter(differs),
      ...own.filter((part) => !differs(part) && !part.setting),
    ]
      .map((part) => part.words)
      .join(", ")
  )
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
    figure: (figures) => figure(formatShare(figures.pnl_share)),
    change: (deltas) => shareChange(deltas.pnl_share),
  },
  {
    id: "profit-factor",
    label: "Profit factor",
    figure: (figures) => orNone(figures.profit_factor, formatFigure),
    change: (deltas) => figureChange(deltas.profit_factor),
  },
  {
    id: "expectancy-r",
    label: "Expectancy in R",
    figure: (figures) => orNone(figures.expectancy_r, formatFigure),
    change: (deltas) => figureChange(deltas.expectancy_r),
  },
  {
    id: "win-rate",
    label: "Win rate",
    figure: (figures) => orNone(figures.win_rate, formatShare),
    change: (deltas) =>
      deltas.win_rate === null ? NONE : shareChange(deltas.win_rate),
  },
  {
    id: "max-drawdown",
    label: "Max drawdown",
    figure: (figures, currency) =>
      figure(formatMoney(figures.max_drawdown, currency)),
    change: (deltas, currency) => moneyChange(deltas.max_drawdown, currency),
  },
  {
    id: "max-drawdown-share",
    label: "Max drawdown of the capital",
    figure: (figures) => figure(formatShare(figures.max_drawdown_share)),
    change: (deltas) => shareChange(deltas.max_drawdown_share),
  },
  {
    id: "sharpe",
    label: "Sharpe",
    figure: (figures) => orNone(figures.sharpe, formatFigure),
    change: (deltas) => figureChange(deltas.sharpe),
  },
  {
    id: "trades",
    label: "Trades",
    figure: (figures) => figure(formatCount(figures.trades)),
    change: (deltas) => countChange(deltas.trades),
  },
]
