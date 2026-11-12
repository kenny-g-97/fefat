import { type Timeframe, timeframe, timeframeSeconds } from "@/api/bar-windows"
import type { MonthCoverage, StoredDataset } from "@/api/catalog"
import { formatCount } from "@/ui/figures"

/** Datasets grouped under a name, a root or a provider, in the API's order. */
export type Grouped = Readonly<{
  name: string
  datasets: readonly StoredDataset[]
}>

/** How a month of a quality report is held: every session with records, some, or none. */
export type MonthHeld = "every" | "some" | "none"

const UNITS: Readonly<Record<string, string>> = {
  s: "second",
  m: "minute",
  h: "hour",
  d: "day",
}
const SECONDS: Readonly<Record<string, number>> = {
  s: 1,
  m: 60,
  h: 3600,
  d: 86_400,
}

/** `datasets` grouped by their provider, each provider once, in the order the API lists them. */
export function byProvider(
  datasets: readonly StoredDataset[]
): readonly Grouped[] {
  return grouped(datasets, (dataset) => dataset.provider)
}

/** `datasets` grouped by their root, each root once, in the order the API lists them. */
export function byRoot(datasets: readonly StoredDataset[]): readonly Grouped[] {
  return grouped(datasets, (dataset) => dataset.root)
}

/** What a dataset's fidelity holds, in words: Trades, TBBO, or 1-minute bars. */
export function fidelityLabel(fidelity: string): string {
  if (fidelity === "trades") {
    return "Trades"
  }
  if (fidelity === "tbbo") {
    return "TBBO"
  }
  const parts = /^(\d+)([smhd])$/.exec(fidelity)
  if (parts === null) {
    throw new Error(
      `Expected a fidelity such as trades or 1m, got ${JSON.stringify(fidelity)}.`
    )
  }
  return `${parts[1]}-${UNITS[parts[2]]} bars`
}

/** The timeframe a provider's chart opens at: five minutes, or, where its finest bars are
 * longer, the first the chart offers that a whole number of them builds; five minutes still
 * where none does, which the chart then refuses in the SDK's words. */
export function chartTimeframe(datasets: readonly StoredDataset[]): Timeframe {
  const finest = Math.min(
    ...datasets.map((dataset) => fidelitySeconds(dataset.fidelity))
  )
  const opening = timeframeSeconds("5m")
  const built = timeframe.options.find(
    (each) =>
      timeframeSeconds(each) >= opening && timeframeSeconds(each) % finest === 0
  )
  return built === undefined ? "5m" : built
}

/** The seconds a bar of `fidelity` spans, one for prints, which build any timeframe. */
function fidelitySeconds(fidelity: string): number {
  if (fidelity === "trades" || fidelity === "tbbo") {
    return 1
  }
  const parts = /^(\d+)([smhd])$/.exec(fidelity)
  const unit = parts === null ? undefined : SECONDS[parts[2]]
  if (parts === null || unit === undefined) {
    throw new Error(
      `Expected a fidelity such as trades or 1m, got ${JSON.stringify(fidelity)}.`
    )
  }
  return Number(parts[1]) * unit
}

/** How `month` is held: every session with records, some, or none. */
export function monthHeld(month: MonthCoverage): MonthHeld {
  if (month.with_records === 0) {
    return "none"
  }
  return month.with_records === month.sessions ? "every" : "some"
}

/** A month in words, its cell's name for a screen reader: 2026-03: 21 of 22 sessions with
 * records, 1 finding. */
export function monthLabel(month: MonthCoverage): string {
  const findings =
    month.findings === 0 ? "no findings" : counted(month.findings, "finding")
  const flagged =
    month.vendor_flagged === 0
      ? ""
      : `, ${counted(month.vendor_flagged, "session")} the vendor flagged`
  return `${month.month}: ${formatCount(month.with_records)} of ${formatCount(month.sessions)} sessions with records, ${findings}${flagged}`
}

function counted(count: number, noun: string): string {
  return `${formatCount(count)} ${noun}${count === 1 ? "" : "s"}`
}

function grouped(
  datasets: readonly StoredDataset[],
  nameOf: (dataset: StoredDataset) => string
): readonly Grouped[] {
  const names = [...new Set(datasets.map(nameOf))]
  return names.map((name) => ({
    name,
    datasets: datasets.filter((dataset) => nameOf(dataset) === name),
  }))
}
