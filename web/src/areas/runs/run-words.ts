import type { ListedRun } from "@/api/runs"
import { counted } from "@/ui/figures"

/** A run's slippage in ticks: `1 tick`, or `1 market, 2 stop` where the two differ. */
export function slippageWords(run: ListedRun): string {
  const { market, stop } = run.settings.slippage_ticks
  return market === stop
    ? counted(market, "tick")
    : `${market} market, ${stop} stop`
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
