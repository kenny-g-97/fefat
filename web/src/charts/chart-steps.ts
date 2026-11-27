import type { IChartApi } from "lightweight-charts"
import { type KeyboardEvent, type RefObject, useRef } from "react"
import { firstCandles } from "./chart-handle"
import { keyAction } from "./chart-keys"
import { moved } from "./chart-options"
import { chartTime } from "./chart-time"
import type { Drawn } from "./drawn-series"

/** The keys of a focused chart (`keyAction`) and its crosshair: `pressed` pans, zooms, or steps
 * the crosshair a bar, `pointed` hears the crosshair the pointer moves, and `left`, as the focus
 * leaves the chart, takes away a crosshair the keys placed, as Escape does; each tells
 * `onCrosshairMove` the bar under the crosshair, none once it is gone. */
export function useChartKeys(
  chart: RefObject<IChartApi | null>,
  drawn: RefObject<Map<string, Drawn>>,
  onCrosshairMove: ((index: number | null) => void) | undefined
) {
  const crosshair = useRef<number | null>(null)
  const keyed = useRef(false)
  const report = (index: number | null, byTheKeys: boolean) => {
    crosshair.current = index
    keyed.current = byTheKeys && index !== null
    onCrosshairMove?.(index)
  }
  const left = () => {
    if (chart.current !== null && keyed.current) {
      report(crosshairCleared(chart.current), false)
    }
  }
  const pressed = (event: KeyboardEvent<HTMLElement>) => {
    const current = chart.current
    const action = keyAction(event.key, event.shiftKey)
    if (event.key === "Escape") {
      left()
    }
    if (current === null || action === undefined) {
      return
    }
    event.preventDefault()
    if (action.kind !== "step") {
      moved(current, action)
      return
    }
    const from = crosshair.current
    const index = crosshairStepped(current, drawn.current, from, action.bars)
    if (index !== null) {
      report(index, true)
    }
  }
  return {
    pressed,
    left,
    pointed: (index: number | null) => report(index, false),
  }
}

/** Step the crosshair of `chart` by `bars` from the bar `from` of its first candle series, or
 * onto the last bar in view where it stands on none, that bar kept in view: the index it stands
 * on, none where the chart has no bars. The library tells no crosshair move it did not see the
 * pointer make, so the caller reports it (web/DESIGN.md, Patterns, Price chart). */
export function crosshairStepped(
  chart: IChartApi,
  drawn: ReadonlyMap<string, Drawn>,
  from: number | null,
  bars: -1 | 1
): number | null {
  const candles = firstCandles(drawn)
  const last = candles === undefined ? -1 : candles.last.time.length - 1
  if (candles === undefined || last < 0) {
    return null
  }
  const index =
    from === null
      ? lastInView(chart, last)
      : Math.min(last, Math.max(0, from + bars))
  chart.setCrosshairPosition(
    candles.last.close[index],
    chartTime(candles.last.time[index]),
    candles.api
  )
  keptInView(chart, index)
  return index
}

/** Take away a crosshair the keys placed: none stands, which the caller reports. */
export function crosshairCleared(chart: IChartApi): null {
  chart.clearCrosshairPosition()
  return null
}

/** The last bar of the view, of the `last` there are. */
function lastInView(chart: IChartApi, last: number): number {
  const range = chart.timeScale().getVisibleLogicalRange()
  return range === null
    ? last
    : Math.min(last, Math.max(0, Math.floor(range.to)))
}

/** Move the view just enough that the bar `index` stands in it. */
function keptInView(chart: IChartApi, index: number): void {
  const timeScale = chart.timeScale()
  const range = timeScale.getVisibleLogicalRange()
  if (range === null) {
    return
  }
  const shift =
    index < range.from
      ? index - range.from
      : index > range.to
        ? index - range.to
        : 0
  if (shift !== 0) {
    timeScale.setVisibleLogicalRange({
      from: range.from + shift,
      to: range.to + shift,
    })
  }
}
