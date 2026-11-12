import { queryOptions } from "@tanstack/react-query"
import {
  type BarColumns,
  type BarWindow,
  joinedBars,
  type Timeframe,
} from "./bar-windows"
import { api } from "./client"
import { answer } from "./problems"
import type { components } from "./schema"

/** The prices a chart's bars carry: adjusted, as features read a spliced series, or raw, at
 * each bar's contract's traded prices. */
export type BarPrices = components["schemas"]["BarPrices"]

/** A series of bars the chart draws: a root, such as MES, or a contract alone, such as
 * MESM2026, in a timeframe, at its prices, from a provider the trader named or else the
 * catalog's recommended source among those that hold it. */
export type Series = Readonly<{
  instrument: string
  timeframe: Timeframe
  prices: BarPrices
  provider: string | null
}>

type BarsPage = components["schemas"]["BarsPage"]

/** A window's bars, the provider they come from, and what `load` warns of them. */
export type WindowBars = Readonly<{
  bars: BarColumns
  provider: string
  warnings: readonly string[]
}>

/** The trade dates the series' data holds, with its provider: read each time a chart opens, so
 * that its newest window follows the data. */
export function barsSpanQuery(series: Series) {
  return queryOptions({
    queryKey: [
      "market",
      "span",
      series.instrument,
      series.timeframe,
      series.provider,
    ],
    queryFn: async ({ signal }) =>
      answer(
        await api.GET("/v1/market/bars/span", {
          params: { query: { ...seriesQuery(series) } },
          signal,
        })
      ),
  })
}

/** The bars of one window of the series, kept for the session once read, since a window's bars
 * change only with an import, and dropped a few minutes after no chart shows them. */
export function barsWindowQuery(series: Series, window: BarWindow) {
  return queryOptions({
    queryKey: ["market", "bars", series, window.from, window.to],
    queryFn: ({ signal }) => windowBars(series, window, signal),
    staleTime: Infinity,
  })
}

/** Every page of the window, each request at most the 20,000 bars a page holds, the next asked
 * from where the last said it opens. */
async function windowBars(
  series: Series,
  window: BarWindow,
  signal: AbortSignal
): Promise<WindowBars> {
  const pages: BarsPage[] = []
  let from: string | null = window.from
  while (from !== null) {
    const page: BarsPage = answer(
      await api.GET("/v1/market/bars", {
        params: {
          query: {
            ...seriesQuery(series),
            from,
            to: window.to,
            prices: series.prices,
          },
        },
        signal,
      })
    )
    pages.push(page)
    from = page.next_from
  }
  const first = pages[0]
  if (first === undefined) {
    throw new Error(`Expected a page of ${series.instrument}'s bars, got none.`)
  }
  return {
    bars: joinedBars(pages.map((page) => page.bars).toReversed()),
    provider: first.provider,
    warnings: [...new Set(pages.flatMap((page) => page.warnings))],
  }
}

function seriesQuery(series: Series) {
  const named = series.provider === null ? {} : { provider: series.provider }
  return {
    instrument: series.instrument,
    timeframe: series.timeframe,
    ...named,
  }
}
