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

/** What a run trades, as its settings name it: `MNQ in 5m bars`; the instrument alone for a run
 * of no saved version, whose timeframe the list does not hold, and nothing for one saved before a
 * run named its instrument. */
export function tradedWords({ strategy, settings }: TradedRun): string {
  const traded = settings.instrument ?? ""
  return strategy === null ? traded : `${traded} in ${strategy.timeframe} bars`
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

/** A run with its dates, as a page's line under its title names it. */
type DatedRun = TradedRun & Pick<ListedRun, "start" | "end">

/** What a run's page says of it under its title: its version, what it trades, and its dates. */
export function runLine(run: DatedRun): string {
  const version =
    run.strategy === null
      ? "No saved version"
      : `Version ${run.strategy.version}`
  return lineOf(version, run)
}

/** What the page of a run's results in full says of it under its title (step 5.22): its strategy
 * and version, what it trades, and its dates, `demo version 2, MNQ in 5m bars, 2026-03-06 to
 * 2026-03-09`. */
export function resultsLine(run: DatedRun): string {
  const version =
    run.strategy === null
      ? "No saved version"
      : `${run.strategy.name} version ${run.strategy.version}`
  return lineOf(version, run)
}

/** A saved run as its checkbox names it for a comparison (step 5.10): its strategy and version,
 * what it trades, its dates, and the parameters that tell it apart from another run of them. */
export function choiceWords(
  run: DatedRun & Pick<ListedRun, "parameters">
): string {
  return [resultsLine(run), parameterWords(run)]
    .filter((words) => words !== "")
    .join(", ")
}

/** `version`, what `run` trades, and its dates, each left out where it is empty. */
function lineOf(version: string, run: DatedRun): string {
  return [version, tradedWords(run), `${run.start} to ${run.end}`]
    .filter((words) => words !== "")
    .join(", ")
}

/** How a launch came to the run its page shows, or null where nothing needs saying: that FEAT
 * found it saved, `cached`, and, where it stands under another version than the one launched,
 * `askedVersion`, which one, since two versions whose code gives the same signals on one
 * instrument are one run (D-11, D-114). */
export function foundWords(
  { strategy }: Pick<ListedRun, "strategy">,
  cached: boolean,
  askedVersion: string | undefined
): string | null {
  if (askedVersion === undefined || strategy?.version_id === askedVersion) {
    return cached ? "FEAT found this run saved and opened it." : null
  }
  const under =
    strategy === null
      ? "with no version in the library"
      : `under ${strategy.name}, version ${strategy.version}`
  return cached
    ? `FEAT found this run saved ${under}, whose code gives the same signals, and opened it.`
    : `FEAT followed this run ${under}, whose code gives the same signals, rather than run it twice.`
}
