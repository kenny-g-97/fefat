import { barSeconds, type Timeframe, timeframe } from "@/api/bar-windows"
import type { CatalogStatus, MonthCoverage, StoredDataset } from "@/api/catalog"
import { formatCount } from "@/ui/figures"

/** Datasets grouped under a name, a root or a provider, in the API's order. */
export type Grouped = Readonly<{
  name: string
  datasets: readonly StoredDataset[]
}>

/** A product the catalog lists, with the datasets that hold it. */
export type CatalogProduct = CatalogStatus["products"][number]

/** An instrument's data from one provider, as the trader imported it and as the Data page lists
 * it: the store's datasets of it, one per kind of data; those kinds in words; the first and the
 * last trade date among them; its quality, stale once a dataset outgrew the report the others
 * still read clean; and its product, where the catalog lists the instrument. */
export type ImportedDataset = Readonly<{
  root: string
  provider: string
  stored: readonly [StoredDataset, ...StoredDataset[]]
  kinds: string
  from: string
  to: string
  quality: StoredDataset["quality"]
  product: CatalogProduct | null
}>

/** The data the store holds, an instrument's from one provider at a time, in the API's order:
 * the catalog's products, then the roots it does not list. */
export function importedDatasets(
  catalog: CatalogStatus
): readonly ImportedDataset[] {
  const listed = catalog.products.flatMap((product) =>
    byProvider(product.datasets).map((held) => imported(held, product))
  )
  const unlisted = byRoot(catalog.unlisted).flatMap((root) =>
    byProvider(root.datasets).map((held) => imported(held, null))
  )
  return [...listed, ...unlisted]
}

/** The catalog's products that hold no data yet. */
export function notImported(catalog: CatalogStatus): readonly CatalogProduct[] {
  return catalog.products.filter((product) => product.datasets.length === 0)
}

/** How a month of a quality report is held: every session with records, some, or none. */
export type MonthHeld = "every" | "some" | "none"

const UNITS: Readonly<Record<string, string>> = {
  s: "second",
  m: "minute",
  h: "hour",
  d: "day",
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
    ...datasets.map((dataset) =>
      dataset.fidelity === "trades" || dataset.fidelity === "tbbo"
        ? 1
        : barSeconds(dataset.fidelity)
    )
  )
  const opening = barSeconds("5m")
  const built = timeframe.options.find(
    (each) => barSeconds(each) >= opening && barSeconds(each) % finest === 0
  )
  return built === undefined ? "5m" : built
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

function imported(
  held: Grouped,
  product: CatalogProduct | null
): ImportedDataset {
  const [first, ...rest] = held.datasets
  if (first === undefined) {
    throw new Error(`Expected datasets of the provider ${held.name}, got none.`)
  }
  const stored: ImportedDataset["stored"] = [first, ...rest]
  return {
    root: first.root,
    provider: held.name,
    stored,
    kinds: stored.map((each) => fidelityLabel(each.fidelity)).join(", "),
    from: stored.reduce(
      (earliest, each) =>
        each.first_trade_date < earliest ? each.first_trade_date : earliest,
      first.first_trade_date
    ),
    to: stored.reduce(
      (latest, each) =>
        each.last_trade_date > latest ? each.last_trade_date : latest,
      first.last_trade_date
    ),
    quality: stored.some((each) => each.quality === "stale")
      ? "stale"
      : first.quality,
    product,
  }
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
