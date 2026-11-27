import { type UseQueryResult, useQueries } from "@tanstack/react-query"
import { useCallback, useState } from "react"
import {
  type BarWindow,
  grownRange,
  readAround,
  type WindowRange,
} from "@/api/bar-windows"
import {
  type ChartWindow,
  joinedWindows,
  runChartWindowQuery,
} from "@/api/run-chart"
import type { VisibleBars } from "@/charts/PriceChart"

/** The windows read so far around the centre: the chart they give, joined, none while the centre
 * is not read; which of them it joins; whether every window asked for is read; and the first that
 * failed. */
type ReadWindows = Readonly<{
  chart: ChartWindow | null
  around: Readonly<{ from: number; to: number }> | null
  settled: boolean
  failure: Readonly<{ error: Error; retry: () => void }> | undefined
}>

/** The run's chart a window at a time (web/DESIGN.md, Patterns, Trade review chart): `windows`,
 * newest first, on the grid the Data chart cuts its own on, read from the window at `centre`,
 * the selected trade's, and then one older or newer as the view nears either end of the bars
 * read, the whole run's windows never asked at once, so that a run of 200,000 bars stays
 * responsive; a new centre outside those asked starts over from it, the others kept in the
 * cache. `span` gives the dates the bars read cover, and `grow` hears the view's bars. */
export function useRunChartWindows(
  runKey: string,
  windows: readonly BarWindow[],
  centre: number
) {
  const [range, setRange] = useState<WindowRange>({
    newest: centre,
    oldest: centre,
  })
  const shown =
    range.newest <= centre && centre <= range.oldest
      ? range
      : { newest: centre, oldest: centre }
  const asked = windows.slice(shown.newest, shown.oldest + 1)
  const at = centre - shown.newest
  const combine = useCallback(
    (results: UseQueryResult<ChartWindow>[]) => readWindows(results, at),
    [at]
  )
  const read = useQueries({
    queries: asked.map((each) => runChartWindowQuery(runKey, each)),
    combine,
  })
  const around = read.around
  const first = around === null ? undefined : asked.at(around.to)
  const last = around === null ? undefined : asked.at(around.from)
  const grow = (visible: VisibleBars) => {
    if (!read.settled) {
      return
    }
    const next = grownRange(shown, visible, windows.length)
    if (next !== shown) {
      setRange(next)
    }
  }
  return {
    ...read,
    span:
      first === undefined || last === undefined
        ? null
        : { first: first.from, last: last.to },
    windows: `${asked.length} of ${windows.length}`,
    grow,
  }
}

function readWindows(
  results: readonly UseQueryResult<ChartWindow>[],
  at: number
): ReadWindows {
  const loaded = results.map((result) => result.data)
  const around = readAround(loaded, at)
  const failed = results.find((result) => result.status === "error")
  const joined =
    around === null
      ? []
      : loaded
          .slice(around.from, around.to + 1)
          .flatMap((each) => (each === undefined ? [] : [each]))
  return {
    chart: joined.length === 0 ? null : joinedWindows(joined),
    around,
    settled: results.every((result) => result.status === "success"),
    failure:
      failed === undefined
        ? undefined
        : { error: failed.error, retry: () => void failed.refetch() },
  }
}
