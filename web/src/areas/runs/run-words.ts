import type { ListedRun } from "@/api/runs"
import { counted } from "@/ui/figures"

/** A run's slippage in ticks: `1 tick`, or `1 market, 2 stop` where the two differ. */
export function slippageWords(run: ListedRun): string {
  const { market, stop } = run.settings.slippage_ticks
  return market === stop
    ? counted(market, "tick")
    : `${market} market, ${stop} stop`
}

/** The parameters a run ran with, as a row of the list names them: `lookback 12, stop_atr 1.5`,
 * which tell apart two runs of one version; empty for a run that names none. */
export function parameterWords(run: Pick<ListedRun, "parameters">): string {
  return Object.entries(run.parameters)
    .map(([name, value]) => `${name} ${parameterText(value)}`)
    .join(", ")
}

/** A parameter's value as text: a number, a word, or a flag as it is, anything nested as JSON. */
export function parameterText(value: unknown): string {
  return typeof value === "object" ? JSON.stringify(value) : String(value)
}

/** What a run's page says of it under its title: its version, what it trades, and its dates. */
export function runLine(run: ListedRun): string {
  const dates = `${run.start} to ${run.end}`
  if (run.strategy === null) {
    return `No saved version, ${dates}`
  }
  const { version, instrument, timeframe } = run.strategy
  return `Version ${version}, ${instrument} in ${timeframe} bars, ${dates}`
}
