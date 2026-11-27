import type { IChartApi } from "lightweight-charts"
import type { RefObject } from "react"
import { type ChartTime, chartTime } from "./chart-time"
import type { Drawn } from "./drawn-series"

/** A point of the chart in pixels from the top left of its first pane. */
export type ChartPoint = Readonly<{ x: number; y: number }>

/** What a page asks of its price chart, through `PriceChart`'s `ref`: to show the bars from one
 * time to another, a trade's from its entry's bar to its exit's, and where a time and a price of
 * the first candle series stand in the chart, for what the page draws over it. */
export type PriceChartHandle = Readonly<{
  showBars: (first: ChartTime, last: ChartTime) => boolean
  locate: (time: ChartTime, price: number) => ChartPoint | null
}>

type DrawnCandles = Extract<Drawn, Readonly<{ kind: "candles" }>>

/** The fewest bars the view holds when it shows some, so that a short trade stands among the
 * bars around it. */
const LEAST_BARS_SHOWN = 80
/** How much wider than the bars shown the view is, so that they stand clear of its edges. */
const MARGIN = 1.5

/** The handle of the chart `chart` holds once created, whose series `drawn` holds. */
export function chartHandle(
  chart: RefObject<IChartApi | null>,
  drawn: RefObject<Map<string, Drawn>>
): PriceChartHandle {
  return {
    showBars: (first, last) => {
      const candles = firstCandles(drawn.current)
      const created = chart.current
      const from = candles === undefined ? -1 : candles.last.time.indexOf(first)
      const to = candles === undefined ? -1 : candles.last.time.indexOf(last)
      if (created === null || from === -1 || to === -1) {
        return false
      }
      const width = Math.max(LEAST_BARS_SHOWN, (to - from + 1) * MARGIN)
      const centre = (from + to) / 2
      created.timeScale().setVisibleLogicalRange({
        from: centre - width / 2,
        to: centre + width / 2,
      })
      return true
    },
    locate: (time, price) => {
      const candles = firstCandles(drawn.current)
      const created = chart.current
      if (created === null || candles === undefined) {
        return null
      }
      const x = created.timeScale().timeToCoordinate(chartTime(time))
      const y = candles.api.priceToCoordinate(price)
      const pane = created.panes().at(0)
      if (x === null || y === null || pane === undefined) {
        return null
      }
      const inside =
        x >= 0 &&
        x <= created.timeScale().width() &&
        y >= 0 &&
        y <= pane.getHeight()
      return inside ? { x, y } : null
    },
  }
}

/** The view of `chart` as `drawn` stands, to put back once new bars are drawn: the same bars in
 * view, however many arrived before them. The library keeps the newest bar's place as a series'
 * bars are set anew, which would move a view scrolled back to the end of the bars a newer window
 * brings (the trade review's, step 5.9); the chart viewer's older windows keep their view as
 * they did. */
export function keptView(
  chart: IChartApi,
  drawn: ReadonlyMap<string, Drawn>
): (now: ReadonlyMap<string, Drawn>) => void {
  const before = firstCandles(drawn)
  const first = before === undefined ? undefined : before.last.time.at(0)
  const range = chart.timeScale().getVisibleLogicalRange()
  return (now) => {
    const after = firstCandles(now)
    if (range === null || first === undefined || after === undefined) {
      return
    }
    const shift = after.last.time.indexOf(first)
    if (shift >= 0) {
      chart.timeScale().setVisibleLogicalRange({
        from: range.from + shift,
        to: range.to + shift,
      })
    }
  }
}

/** The first candle series `drawn` holds, whose bars the chart's view and keys count. */
export function firstCandles(
  drawn: ReadonlyMap<string, Drawn>
): DrawnCandles | undefined {
  for (const each of drawn.values()) {
    if (each.kind === "candles") {
      return each
    }
  }
  return undefined
}
