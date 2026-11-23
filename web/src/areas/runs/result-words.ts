import type { SampleSize } from "@/api/run-results"
import { counted } from "@/ui/figures"

const SAMPLE_SIZES: Readonly<Record<SampleSize, string>> = {
  below_minimum: "under the 30 a sample needs at the least",
  minimum: "past the minimum of 30, under the 100 preferred",
  preferred: "past the 100 preferred, under the 200 of high confidence",
  high_confidence: "past the 200 of high confidence",
}

/** A word of the API in sentence case, such as an exit reason, a weekday, or a dimension of the
 * robustness summary: `target_1` reads `Target 1`, `risk_management` `Risk management`. */
export function sentenceCase(word: string): string {
  const spaced = word.replaceAll("_", " ")
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
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
