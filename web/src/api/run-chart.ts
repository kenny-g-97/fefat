import { queryOptions } from "@tanstack/react-query"
import { type BarColumns, type BarWindow, joinedBars } from "./bar-windows"
import { api } from "./client"
import { answer } from "./problems"
import type { components } from "./schema"

/** A page of a saved run's chart, as `GET /v1/runs/{run}/chart` sends it (step 5.9). */
export type ChartPage = components["schemas"]["ChartPage"]
/** A trade a page of the chart shows, every fill of it with the bar it lies on. */
export type ChartTrade = components["schemas"]["ChartTrade"]
/** A fill of a trade, as the fills ledger holds it. */
export type ChartFill = components["schemas"]["ChartFill"]
/** One of the strategy's features beside the bars. */
export type ChartFeature = components["schemas"]["ChartFeature"]

/** The run's chart over one window of its dates, or several in a row, its pages joined: its bars,
 * the strategy's features beside them, the trades they show, the instrument's tick, and what
 * `load` warns of. */
export type ChartWindow = Readonly<{
  bars: BarColumns
  features: readonly ChartFeature[]
  trades: readonly ChartTrade[]
  tickSize: string
  warnings: readonly string[]
}>

/** The run's chart over `window`, every page of it, never asked again once read, since a saved
 * run's bars change only with an import. */
export function runChartWindowQuery(runKey: string, window: BarWindow) {
  return queryOptions({
    queryKey: ["run-results", runKey, "chart", window.from, window.to],
    queryFn: ({ signal }) => chartWindow(runKey, window, signal),
    staleTime: Infinity,
  })
}

async function chartWindow(
  runKey: string,
  window: BarWindow,
  signal: AbortSignal
): Promise<ChartWindow> {
  const pages: ChartPage[] = []
  let from: string | null = window.from
  while (from !== null) {
    const page: ChartPage = answer(
      await api.GET("/v1/runs/{run}/chart", {
        params: { path: { run: runKey }, query: { from, to: window.to } },
        signal,
      })
    )
    pages.push(page)
    from = page.next_from
  }
  const first = pages[0]
  if (first === undefined) {
    throw new Error(`Expected a page of run ${runKey}'s chart, got none.`)
  }
  return joinedWindows(
    pages.toReversed().map((page) => ({
      bars: page.bars,
      features: page.features,
      trades: page.trades,
      tickSize: page.tick_size,
      warnings: page.warnings,
    }))
  )
}

/** `windows`, newest first, each ending before the newer begins, as one: their bars oldest first,
 * each feature's values in the same order, each trade once, its fills on whichever window's
 * bars they lie on, and each warning once. */
export function joinedWindows(windows: readonly ChartWindow[]): ChartWindow {
  const newest = windows.at(0)
  if (newest === undefined) {
    throw new Error("Expected a window of the chart, got none.")
  }
  const oldestFirst = windows.toReversed()
  return {
    bars: joinedBars(windows.map((each) => each.bars)),
    features: newest.features.map((feature) => ({
      ...feature,
      values: oldestFirst.flatMap((each) => featureValues(each, feature.name)),
    })),
    trades: mergedTrades(oldestFirst.flatMap((each) => each.trades)),
    tickSize: newest.tickSize,
    warnings: [...new Set(oldestFirst.flatMap((each) => each.warnings))],
  }
}

/** The values of the feature `name` in `window`, one a bar, none for a window that lacks it. */
function featureValues(window: ChartWindow, name: string): (number | null)[] {
  const found = window.features.find((feature) => feature.name === name)
  return found === undefined
    ? window.bars.time.map(() => null)
    : [...found.values]
}

/** `trades`, each once by its entry order in the order of their rows: a trade two windows show
 * holds each fill on the bar either window gives it, the server sending every fill of a trade
 * with each window and the bar only where the fill lies on that window. */
export function mergedTrades(
  trades: readonly ChartTrade[]
): readonly ChartTrade[] {
  const merged = new Map<number, ChartTrade>()
  for (const trade of trades) {
    const seen = merged.get(trade.entry_order)
    merged.set(
      trade.entry_order,
      seen === undefined
        ? trade
        : {
            ...seen,
            fills: seen.fills.map((fill, index) => {
              const other = trade.fills.at(index)
              return fill.bar_time === null && other !== undefined
                ? { ...fill, bar_time: other.bar_time }
                : fill
            }),
          }
    )
  }
  return [...merged.values()].toSorted((one, other) => one.trade - other.trade)
}
