import type { MarkerTone } from "./chart-look"
import type { ChartTime } from "./chart-time"

/** A marker on a candle series: where, its words, above or below its bar, its shape, and how it
 * reads. */
export type ChartMarker = Readonly<{
  time: ChartTime
  text: string
  position: "above" | "below"
  shape: "arrowUp" | "arrowDown" | "circle" | "square"
  tone: MarkerTone
}>

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
