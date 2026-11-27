import { infiniteQueryOptions, useMutation } from "@tanstack/react-query"
import { api } from "./client"
import { answer } from "./problems"
import type { components, paths } from "./schema"

/** A trade of a saved run as the table shows it, every figure the API's (step 5.8). */
export type Trade = components["schemas"]["TradeRow"]
/** The answer of one SELECT over a run's artifacts. */
export type QueryAnswer = components["schemas"]["QueryAnswer"]
/** What the trades' route asks of a run's trades: their filters, their order, a page's cursor,
 * and its size. */
type TradesAsked = NonNullable<
  paths["/v1/runs/{run}/trades"]["get"]["parameters"]["query"]
>
/** Which trades a table shows, in which order, as its page's address keeps them. */
export type TradesShown = Omit<TradesAsked, "cursor" | "limit">
/** What a trade is ordered by. */
export type TradeSort = NonNullable<TradesShown["sort"]>

/** How many trades a page of the table reads at a time: five windows of rows, so that a scroll
 * reads a page well before it reaches the rows it holds. */
export const TRADES_PER_PAGE = 200

async function readTrades(
  runKey: string,
  shown: TradesShown,
  cursor: string | null
) {
  return answer(
    await api.GET("/v1/runs/{run}/trades", {
      params: {
        path: { run: runKey },
        query: {
          ...shown,
          limit: TRADES_PER_PAGE,
          ...(cursor === null ? {} : { cursor }),
        },
      },
    })
  )
}

/** The trades of the saved run `runKey` that `shown` keeps, in its order, a page at a time; a
 * saved run never changes, so a page read is kept while the tab shows it. */
export function runTradesQuery(runKey: string, shown: TradesShown) {
  return infiniteQueryOptions({
    queryKey: ["run-results", runKey, "trades", shown],
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      readTrades(runKey, shown, pageParam),
    initialPageParam: null,
    getNextPageParam: (page) => page.next_cursor,
    staleTime: Infinity,
  })
}

/** The query string of `shown`, its filters left out where they ask nothing. */
function queryText(shown: TradesShown): string {
  const asked = Object.entries(shown).flatMap(([name, value]) =>
    value === undefined || value === null ? [] : [[name, String(value)]]
  )
  const text = new URLSearchParams(asked).toString()
  return text === "" ? "" : `?${text}`
}

/** The address of the CSV of the trades of the saved run `runKey` that `shown` keeps, in its
 * order, which the server answers as a file to download. */
export function tradesFileAddress(runKey: string, shown: TradesShown): string {
  return `/v1/runs/${runKey}/trades.csv${queryText(shown)}`
}

/** The address of the CSV of the fills of the saved run `runKey`, one row an execution. */
export function executionsFileAddress(runKey: string): string {
  return `/v1/runs/${runKey}/executions.csv`
}

/** Ask one SELECT of the artifacts of the saved run `runKey`. */
export function useRunQuery(runKey: string) {
  return useMutation({
    mutationFn: async (sql: string) =>
      answer(
        await api.POST("/v1/runs/{run}/query", {
          params: { path: { run: runKey } },
          body: { sql },
        })
      ),
  })
}
