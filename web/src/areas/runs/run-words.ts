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

/** What a run needs to say what it trades. */
type TradedRun = Readonly<{
  strategy: ListedRun["strategy"]
  settings: Pick<ListedRun["settings"], "instrument">
}>

/** What a run trades: `MNQ in 5m bars`; the instrument alone for a run of no saved version, whose
 * timeframe the list does not hold, and nothing for one saved before a run named its instrument. */
export function tradedWords({ strategy, settings }: TradedRun): string {
  if (strategy === null) {
    return settings.instrument ?? ""
  }
  return `${strategy.instrument} in ${strategy.timeframe} bars`
}

/** A row's line under its figures: what the run trades, since two runs of one version can differ
 * by it, then the parameters it ran with, each left out where it has none. */
export function runDetail(
  run: TradedRun & Pick<ListedRun, "parameters">
): string {
  return [tradedWords(run), parameterWords(run)]
    .filter((words) => words !== "")
    .join(", ")
}

/** What a run's page says of it under its title: its version, what it trades, and its dates. */
export function runLine(run: ListedRun): string {
  const dates = `${run.start} to ${run.end}`
  if (run.strategy === null) {
    return `No saved version, ${dates}`
  }
  return `Version ${run.strategy.version}, ${tradedWords(run)}, ${dates}`
}
