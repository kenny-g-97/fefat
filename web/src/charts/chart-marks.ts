import type { MarkerTone } from "./chart-look"
import type { ChartTime } from "./chart-time"

/** A marker on a candle series: where, its words, above or below its bar, its shape, and how it
 * reads; with a `price`, above or below that price rather than its bar, the shape's point on
 * it, as a fill's marker stands at its fill's price; with an `id`, told apart under the pointer
 * (`PriceChart`'s `onMarkerHover`); and with a `size`, as many times the library's own, as the
 * selected trade's fills stand out. */
export type ChartMarker = Readonly<{
  time: ChartTime
  text: string
  position: "above" | "below"
  shape: "arrowUp" | "arrowDown" | "circle" | "square"
  tone: MarkerTone
  price?: number
  id?: string
  size?: number
}>

/** `markers` in the order of their times, those of one time as given: the library finds the
 * markers in view by halving their list, and a pane's marks of several kinds, such as its rolls
 * and a run's fills, come in apart. */
export function inTimeOrder(
  markers: readonly ChartMarker[]
): readonly ChartMarker[] {
  return markers.toSorted((one, other) => timeOrder(one.time, other.time))
}

/** How two times of one time axis compare: opens in seconds by their number, trade dates as
 * their text reads. */
function timeOrder(one: ChartTime, other: ChartTime): number {
  if (typeof one === "number" && typeof other === "number") {
    return one - other
  }
  const [first, second] = [String(one), String(other)]
  return first < second ? -1 : first > second ? 1 : 0
}

/** A session of a chart's bars: the time of its first bar and of its last, and whether it is
 * shaded. */
export type SessionSpan = Readonly<{
  first: ChartTime
  last: ChartTime
  shaded: boolean
}>

/** The sessions of bars by their trade dates, every other one shaded counting back from the
 * newest, which is not, so that older bars arriving never change a session's shade. */
export function sessionSpans(
  time: readonly ChartTime[],
  tradeDate: readonly string[]
): readonly SessionSpan[] {
  const starts = tradeDate.flatMap((date, index) =>
    index === 0 || tradeDate[index - 1] !== date ? [index] : []
  )
  return starts.map((start, session) => {
    const end =
      session + 1 < starts.length ? starts[session + 1] - 1 : time.length - 1
    return {
      first: time[start],
      last: time[end],
      shaded: (starts.length - 1 - session) % 2 === 1,
    }
  })
}

/** A quiet mark above the first bar of each new contract of a spliced series, named by it: where
 * the series rolled. */
export function rollMarks(
  time: readonly ChartTime[],
  contract: readonly string[]
): readonly ChartMarker[] {
  return contract.flatMap((each, index) =>
    index > 0 && contract[index - 1] !== each
      ? [
          {
            time: time[index],
            text: each,
            position: "above",
            shape: "arrowDown",
            tone: "subtle",
          },
        ]
      : []
  )
}
