import { useInfiniteQuery } from "@tanstack/react-query"
import { useMemo } from "react"
import type { Currency } from "@/api/runs"
import { runTradesQuery, type TradeSort, type TradesShown } from "@/api/trades"
import { Button } from "@/ui/button"
import { alignedText, counted, formatCount, placesOfText } from "@/ui/figures"
import { SectionFailure } from "@/ui/section-failure"
import { TRADE_SORTS } from "./run-search"
import { type SortOrder, TradeGrid } from "./TradeGrid"
import type { DecimalColumn } from "./trade-columns"

type TradesTableProps = Readonly<{
  runKey: string
  shown: TradesShown
  filtered: boolean
  everyTrade: number | null
  currency: Currency | null
  visibility: Readonly<Record<string, boolean>>
  onOrder: (sort: TradeSort, order: SortOrder) => void
  onClear: () => void
}>

/** The trade table of a saved run (web/DESIGN.md, Patterns, Trade table): a line in a status
 * region that counts the trades the filters keep, out of `everyTrade` once filtered, or says
 * that none matches with the way back, then the trades, read a page at a time as they scroll
 * into view, under their header row while the first page of an order or a filter is read, so
 * that a sort chosen by the keys keeps its focus; a page that fails to come leaves the rows
 * read above its reason and Try again. */
export function TradesTable({
  runKey,
  shown,
  filtered,
  everyTrade,
  currency,
  visibility,
  onOrder,
  onClear,
}: TradesTableProps) {
  const trades = useInfiniteQuery(runTradesQuery(runKey, shown))
  const read = trades.data === undefined ? null : trades.data
  const total = read === null ? null : totalOf(read.pages)
  const rows = useMemo(
    () => (read === null ? [] : read.pages.flatMap((page) => page.trades)),
    [read]
  )
  const look = useMemo(
    () => ({
      currency,
      entry: decimalColumn(rows.map((trade) => trade.entry_price)),
      exit: decimalColumn(
        rows.flatMap((trade) =>
          trade.exit_price === null ? [] : [trade.exit_price]
        )
      ),
    }),
    [currency, rows]
  )
  const {
    hasNextPage,
    isFetchingNextPage,
    isFetchNextPageError,
    fetchNextPage,
  } = trades
  const readOn = useMemo(
    () => () => {
      if (hasNextPage && !isFetchingNextPage && !isFetchNextPageError) {
        void fetchNextPage()
      }
    },
    [hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage]
  )
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p
          role="status"
          data-testid="trades-count"
          className="min-h-5 text-foreground-secondary"
        >
          {countWords(total, filtered, everyTrade)}
        </p>
        {total === 0 && filtered && (
          <Button variant="ghost" onClick={onClear}>
            Clear filters
          </Button>
        )}
      </div>
      {read === null && trades.status === "error" ? (
        <SectionFailure
          error={trades.error}
          onRetry={() => void trades.refetch()}
          className="min-h-40 justify-center"
        />
      ) : total === 0 ? null : (
        <TradeGrid
          trades={rows}
          total={total}
          look={look}
          visibility={visibility}
          sort={shown.sort === undefined ? TRADE_SORTS[0] : shown.sort}
          order={shown.order === undefined ? "asc" : shown.order}
          onOrder={onOrder}
          onNearEnd={readOn}
          readFor={JSON.stringify(shown)}
        />
      )}
      {trades.status === "error" && isFetchNextPageError && (
        <SectionFailure
          error={trades.error}
          onRetry={() => void fetchNextPage()}
        />
      )}
    </div>
  )
}

/** How many trades the filters keep, which every page of them gives. */
function totalOf(pages: readonly Readonly<{ total: number }>[]): number {
  const first = pages.at(0)
  if (first === undefined) {
    throw new Error("Expected the first page of the trades, got none.")
  }
  return first.total
}

/** What the table's count line says: how many trades the filters keep, out of how many the run
 * made, or that none matches; nothing while the first page is read. */
function countWords(
  total: number | null,
  filtered: boolean,
  everyTrade: number | null
): string {
  if (total === null) {
    return ""
  }
  if (total === 0) {
    return filtered
      ? "No trade matches these filters."
      : "This run made no trade."
  }
  if (filtered && everyTrade !== null) {
    return `${formatCount(total)} of ${counted(everyTrade, "trade")}`
  }
  return counted(total, "trade")
}

/** How a column of decimals lines up among the trades read so far (`DecimalColumn`). */
function decimalColumn(prices: readonly string[]): DecimalColumn {
  const places = prices.reduce(
    (most, price) => Math.max(most, placesOfText(price)),
    0
  )
  const characters = prices.reduce(
    (widest, price) => Math.max(widest, alignedText(price, places).length),
    0
  )
  return { places, characters }
}
