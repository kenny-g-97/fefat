import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import {
  runTradeQuery,
  runTradesQuery,
  type Trade,
  type TradesShown,
} from "@/api/trades"

/** Where the selected trade stands among the trades the table keeps: its place where the table
 * read it, `3 of 18`; further down where the table's filters keep it past the rows read; or out
 * of the table where they hide it. */
export type TradePlace =
  | Readonly<{ kind: "at"; at: number; of: number }>
  | Readonly<{ kind: "further" }>
  | Readonly<{ kind: "hidden" }>

/** The filters of no table, for the read of a trade they hide. */
const EVERY_TRADE: TradesShown = {}

/** The trade the chart shows and the way to the table's next and previous trades (step 5.9): the
 * trade whose row the address names, from the rows the table read, which share its cache, or
 * else read alone under the table's filters, and without them where they hide it, as a link or
 * a reload past the rows read asks; the trade last found for the row while the table reads new
 * rows, as a filter or an order asks; where it stands (`TradePlace`); and `previous` and `next`,
 * which select the table's trade before it and after it, the next page read first at the end
 * of those read, and from no selection the table's first. */
export function useSelectedTrade(
  runKey: string,
  shown: TradesShown,
  row: number | undefined,
  onSelect: (trade: Trade) => void
) {
  const table = useInfiniteQuery(runTradesQuery(runKey, shown))
  const rows = useMemo(
    () =>
      table.data === undefined
        ? []
        : table.data.pages.flatMap((page) => page.trades),
    [table.data]
  )
  const firstPage =
    table.data === undefined ? undefined : table.data.pages.at(0)
  const index =
    row === undefined ? -1 : rows.findIndex((trade) => trade.trade === row)
  const lookUp = row !== undefined && index === -1 && table.status === "success"
  const asked = row === undefined ? 0 : row
  const kept = useQuery({
    ...runTradeQuery(runKey, asked, shown),
    enabled: lookUp,
  })
  const hidden = useQuery({
    ...runTradeQuery(runKey, asked, EVERY_TRADE),
    enabled: lookUp && kept.data === null,
  })
  const lookedUp = kept.data === null ? hidden.data : kept.data
  const found =
    index >= 0 ? rows[index] : lookedUp === undefined ? null : lookedUp
  const [lastFound, setLastFound] = useState<Trade | null>(null)
  if (found !== null && found !== lastFound) {
    setLastFound(found)
  }
  const before = index > 0 ? rows[index - 1] : undefined
  const after =
    row === undefined ? rows.at(0) : index >= 0 ? rows.at(index + 1) : undefined
  const pagesRead = table.data === undefined ? 0 : table.data.pages.length
  const readOn =
    index >= 0 && index === rows.length - 1 && table.hasNextPage
      ? () =>
          void table.fetchNextPage().then((read) => {
            const first = firstOfNewPage(read, pagesRead)
            if (first !== undefined) {
              onSelect(first)
            }
          })
      : null
  return {
    trade: shownTrade(found, lastFound, row),
    place: placeOf(
      index,
      firstPage === undefined ? null : firstPage.total,
      lookUp && kept.data !== undefined ? kept.data !== null : null
    ),
    previous: before === undefined ? null : () => onSelect(before),
    next: after === undefined ? readOn : () => onSelect(after),
  }
}

/** The trade the chart shows for the address's `row`: the one `found` for it, or else the one
 * `kept` from before while it is that row's, as while a new filter's rows are read. */
export function shownTrade<Row extends Readonly<{ trade: number }>>(
  found: Row | null,
  kept: Row | null,
  row: number | undefined
): Row | null {
  if (found !== null) {
    return found
  }
  return kept !== null && kept.trade === row ? kept : null
}

/** Where the trade at `index` among the rows read stands among the table's `total`, or, read
 * alone, whether the table's filters keep it; none while that is not known. */
export function placeOf(
  index: number,
  total: number | null,
  keptByFilters: boolean | null
): TradePlace | null {
  if (index >= 0) {
    return total === null ? null : { kind: "at", at: index + 1, of: total }
  }
  if (keptByFilters === null) {
    return null
  }
  return keptByFilters ? { kind: "further" } : { kind: "hidden" }
}

/** The first row of the page a read of the next page added to the `pagesBefore` read, none
 * where the read failed or added none: TanStack Query answers a failed read with the pages it
 * held, whose last page's first row stands before the selection. */
export function firstOfNewPage<Row>(
  read: Readonly<{
    isError: boolean
    data:
      | Readonly<{ pages: readonly Readonly<{ trades: readonly Row[] }>[] }>
      | undefined
  }>,
  pagesBefore: number
): Row | undefined {
  if (
    read.isError ||
    read.data === undefined ||
    read.data.pages.length <= pagesBefore
  ) {
    return undefined
  }
  return read.data.pages.at(-1)?.trades.at(0)
}
