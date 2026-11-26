import type { DaysExposure, Uncounted } from "@/api/run-results"
import { counted, formatFigure } from "@/ui/figures"

/** Why a figure of a run's market exposure reads None, as a stat card's line says it (step 5.23):
 * the API says which, since the client recomputes no figure. */
const WHY: Readonly<Record<Uncounted, string>> = {
  too_few_days: "Needs 3 days",
  market_never_differed: "The market's days never differed",
  run_never_differed: "The run's days never differed",
}

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
  const figure = (value: number | null) =>
    value === null ? "None" : formatFigure(value)
  const beta =
    side.beta_lots === null ? "None" : `${figure(side.beta_lots)} lots`
  const why =
    side.uncounted === null ? "" : `, ${inSentence(WHY[side.uncounted])}`
  return `Over the ${counted(side.days, "day")} the market ${moved}: correlation ${figure(side.correlation)}, beta ${beta}${why}.`
}

/** Buy and hold's size at the run's volatility, as the table heads its column: `0.49 lots`. */
export function lotsWords(lots: number): string {
  return `${formatFigure(lots)} lots`
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
