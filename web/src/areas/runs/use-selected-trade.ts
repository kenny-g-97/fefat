import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { useMemo } from "react"
import {
  runTradeQuery,
  runTradesQuery,
  type Trade,
  type TradesShown,
} from "@/api/trades"

/** The trade the chart shows and the way to the table's next and previous trades (step 5.9): the
 * trade whose row the address names, from the rows the table read, which share its cache, or
 * else read alone, as a link to a trade the filters hide or the table has not reached asks;
 * where it stands among the trades the table keeps, `3 of 18`, when the table holds it; and
 * `previous` and `next`, which select the table's trade before it and after it, the next page
 * read first at the end of those read, and from no selection the table's first. */
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
  const total = table.data === undefined ? null : table.data.pages[0]?.total
  const index =
    row === undefined ? -1 : rows.findIndex((trade) => trade.trade === row)
  const alone = useQuery({
    ...runTradeQuery(runKey, row === undefined ? 0 : row),
    enabled: row !== undefined && index === -1 && table.status === "success",
  })
  const readAlone =
    row === undefined || alone.data === undefined ? null : alone.data
  const trade = index >= 0 ? rows[index] : readAlone
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
    trade,
    position:
      index >= 0 && total !== undefined && total !== null
        ? { at: index + 1, of: total }
        : null,
    previous: before === undefined ? null : () => onSelect(before),
    next: after === undefined ? readOn : () => onSelect(after),
  }
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
