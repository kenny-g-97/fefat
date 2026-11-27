import { type UseQueryResult, useQueries } from "@tanstack/react-query"
import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react"
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
 * is not read; whether every window asked for is read; and the first that failed. */
type ReadWindows = Readonly<{
  chart: ChartWindow | null
  settled: boolean
  failure: Readonly<{ error: Error; retry: () => void }> | undefined
}>

/** The run's chart a window at a time (web/DESIGN.md, Patterns, Trade review chart): `windows`,
 * newest first, on the grid the Data chart cuts its own on, read from the window at `centre`,
 * the selected trade's, and then one older or newer as the view nears either end of the bars
 * read, the whole run's windows never asked at once, so that a run of 200,000 bars stays
 * responsive; a new centre outside those asked starts over from it, the others kept in the
 * cache. `grow` hears the view's bars, and the bars it heard last are heard again once every
 * window asked is read, since a window of no bars draws nothing that would tell them anew. */
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
  const heard = useRef<VisibleBars | null>(null)
  const grow = (visible: VisibleBars) => {
    heard.current = visible
    if (!read.settled) {
      return
    }
    const next = grownRange(shown, visible, windows.length)
    if (next !== shown) {
      setRange(next)
    }
  }
  const growAgain = useEffectEvent(() => {
    if (heard.current !== null) {
      grow(heard.current)
    }
  })
  useEffect(() => {
    if (read.settled) {
      growAgain()
    }
  }, [read.settled, asked.length])
  return { ...read, grow }
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
    settled: results.every((result) => result.status === "success"),
    failure:
      failed === undefined
        ? undefined
        : { error: failed.error, retry: () => void failed.refetch() },
  }
}
