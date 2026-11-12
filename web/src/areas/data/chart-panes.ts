import type { BarColumns, Timeframe } from "@/api/bar-windows"
import type { CatalogStatus, InstrumentVersion } from "@/api/catalog"
import type { ChartTime } from "@/charts/chart-time"
import { rollMarks } from "@/charts/chart-marks"
import type {
  CandleSeries,
  ChartPane,
  HistogramSeries,
} from "@/charts/drawn-series"

/** A contract the trader typed: none, to chart the root, a contract of the root, or a refusal
 * in words. */
export type ContractChoice =
  | Readonly<{ kind: "root" }>
  | Readonly<{ kind: "contract"; contract: string }>
  | Readonly<{ kind: "refused"; message: string }>

/** The panes the chart viewer draws of `bars`: the candles, each roll of a spliced series marked
 * and every other session shaded, over the volume while the style shows it. A daily bar is
 * placed by its trade date and shades nothing, being a session of its own. */
export function chartPanes(
  bars: BarColumns,
  timeframe: Timeframe,
  volumeShown: boolean
): readonly ChartPane[] {
  const daily = timeframe === "1d"
  const time: readonly ChartTime[] = daily ? bars.trade_date : bars.time
  const candles: CandleSeries = {
    kind: "candles",
    id: "price",
    time,
    open: bars.open,
    high: bars.high,
    low: bars.low,
    close: bars.close,
    ...(daily ? {} : { sessions: bars.trade_date }),
    markers: rollMarks(time, bars.contract),
  }
  const price: ChartPane = { id: "price", stretch: 4, series: [candles] }
  if (!volumeShown) {
    return [price]
  }
  const volume: HistogramSeries = {
    kind: "histogram",
    id: "volume",
    time,
    value: bars.volume,
    rising: bars.close.map((close, index) => close >= bars.open[index]),
  }
  return [price, { id: "volume", stretch: 1, series: [volume] }]
}

/** The roots the store holds data of: the catalog's products first, in its order, then the
 * trader's own. */
export function chartRoots(catalog: CatalogStatus): readonly string[] {
  const products = catalog.products
    .filter((product) => product.datasets.length > 0)
    .map((product) => product.root)
  return [
    ...products,
    ...new Set(catalog.unlisted.map((dataset) => dataset.root)),
  ]
}

/** The providers whose datasets hold `root`, in the catalog's order. */
export function rootProviders(
  catalog: CatalogStatus,
  root: string
): readonly string[] {
  const datasets = [
    ...catalog.products.flatMap((product) => product.datasets),
    ...catalog.unlisted,
  ]
  return [
    ...new Set(
      datasets
        .filter((dataset) => dataset.root === root)
        .map((dataset) => dataset.provider)
    ),
  ]
}

/** The version of `root`'s specification in force last, which the API lists by its first day;
 * none for a root FEAT does not know. */
export function latestVersion(
  versions: readonly InstrumentVersion[],
  root: string
): InstrumentVersion | undefined {
  return versions.filter((version) => version.root === root).at(-1)
}

/** What the trader typed in the contract field of `root`, in capitals: nothing charts the root,
 * and a contract of the root, its month's code and its year, charts it alone. */
export function contractChoice(
  root: string,
  typed: string,
  year: number
): ContractChoice {
  const contract = typed.trim().toUpperCase()
  if (contract === "") {
    return { kind: "root" }
  }
  if (!new RegExp(`^${root}[FGHJKMNQUVXZ][0-9]{4}$`).test(contract)) {
    return {
      kind: "refused",
      message: `Type a contract of ${root}, such as ${root}M${year}.`,
    }
  }
  return { kind: "contract", contract }
}
