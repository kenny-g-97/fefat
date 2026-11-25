import type { MonteCarlo, SampleSize } from "@/api/run-results"
import { counted, moneySign } from "@/ui/figures"

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
