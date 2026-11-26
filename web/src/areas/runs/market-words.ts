import type { DaysExposure, Uncounted } from "@/api/run-results"
import { counted, formatFigure } from "@/ui/figures"
import { figureOrNone } from "./result-words"

/** Why a figure of a run's market exposure reads None, as a stat card's line says it (step 5.23):
 * the API says which, since the client recomputes no figure. */
const WHY: Readonly<Record<Uncounted, string>> = {
  too_few_days: "Needs 3 days",
  market_never_differed: "The market's days never differed",
  run_never_differed: "The run's days never differed",
}

/** Lots at two significant digits, for a size two decimals would write as `0.00`. */
const SMALL_LOTS = new Intl.NumberFormat("en-US", {
  maximumSignificantDigits: 2,
})
/** The least size two decimals write as other than `0.00`. */
const LEAST_AT_TWO_DECIMALS = 0.005

/** The words a sentence takes from its middle on: `The run's` reads `the run's`. */
function inSentence(words: string): string {
  return `${words.charAt(0).toLowerCase()}${words.slice(1)}`
}

/** What a stat of the market exposure is out of: the days it counts, `Over 19 days`, or, where
 * `figure` reads None, why. */
export function exposureDetail(
  figure: number | null,
  { days, uncounted }: Pick<DaysExposure, "days" | "uncounted">
): string {
  if (figure !== null) {
    return `Over ${counted(days, "day")}`
  }
  if (uncounted === null) {
    throw new Error(
      `Expected why a figure over ${counted(days, "day")} reads None, got no reason.`
    )
  }
  return WHY[uncounted]
}

/** The two lines under the stats: the correlation and the beta over the days the market fell,
 * then on a line of its own over those it rose, so that the two read one above the other, each
 * None with why where nothing can be counted. */
export function sidesWords(
  falling: DaysExposure,
  rising: DaysExposure
): string {
  return `${sideWords(falling, "fell")}\n${sideWords(rising, "rose")}`
}

function sideWords(side: DaysExposure, moved: "fell" | "rose"): string {
  if (side.days === 0) {
    return `The market ${moved} on no day.`
  }
  const beta = side.beta_lots === null ? "None" : lotsWords(side.beta_lots)
  const why =
    side.uncounted === null ? "" : `, ${inSentence(WHY[side.uncounted])}`
  return `Over the ${counted(side.days, "day")} the market ${moved}: correlation ${figureOrNone(side.correlation)}, beta ${beta}${why}.`
}

/** Lots as a beta or buy and hold's size reads them: `0.49 lots`, or `0.0035 lots`
 * (`formatLots`). */
export function lotsWords(lots: number): string {
  return `${formatLots(lots)} lots`
}

/** Lots at two decimals, `0.49`, or at two significant digits where two decimals would write a
 * size other than none as `0.00`, as a crypto pair's lots, coins, can be: `0.0035` (the ponytail
 * review). */
export function formatLots(lots: number): string {
  if (lots === 0 || Math.abs(lots) >= LEAST_AT_TWO_DECIMALS) {
    return formatFigure(lots)
  }
  return SMALL_LOTS.format(lots)
}

/** Buy and hold at `lots`, as the legend names it: `Buy and hold, 0.49 lots`. */
export function buyAndHoldLabel(lots: number): string {
  return `Buy and hold, ${lotsWords(lots)}`
}

/** What the table of buy and hold says under it: what it holds and pays, and what its size at
 * the run's volatility keeps, or why it has none. */
export function buyAndHoldNote(uncounted: Uncounted | null): string {
  const held =
    "Buy and hold buys at the run's first mark and holds to its last, paying no fee, slippage, or funding."
  if (uncounted === null) {
    return `${held} At the run's volatility it holds the lots whose days move as much as the run's; its Sharpe and its spell under a peak stay one lot's.`
  }
  return `${held} At the run's volatility it reads None: ${inSentence(WHY[uncounted])}.`
}
