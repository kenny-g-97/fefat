import type { Time, UTCTimestamp } from "lightweight-charts"

/** A bar's place on a chart's time axis: its open in whole seconds since the epoch, UTC, as the
 * API sends it, or, for daily bars, its trade date, 2026-03-06, placed by the session. */
export type ChartTime = number | string

/** What a tick mark of the time axis marks, as Lightweight Charts tells it. */
export type TickMark = "year" | "month" | "day" | "time" | "seconds"

/** `time` as the chart takes it: an open in whole seconds, refused otherwise, or a trade date. */
export function chartTime(time: ChartTime): Time {
  if (typeof time === "string") {
    return time
  }
  if (!isWholeSecond(time)) {
    throw new Error(`Expected a bar's open in whole seconds, got ${time}.`)
  }
  return time
}

/** A time the chart gives back, as the bar's: the chart gives a trade date it was given as text
 * back as its fields. */
export function barTime(time: Time): ChartTime {
  if (typeof time === "number" || typeof time === "string") {
    return time
  }
  return `${time.year}-${two(time.month)}-${two(time.day)}`
}

/** The time the crosshair's label and the readout show: an open in this browser's time zone,
 * 2026-03-06 14:35, as every instant of the app; a trade date as it is. */
export function crosshairTime(time: ChartTime): string {
  if (typeof time === "string") {
    return time
  }
  const instant = new Date(time * 1000)
  return `${localDate(instant)} ${two(instant.getHours())}:${two(instant.getMinutes())}`
}

/** A tick mark's label: a time of day in this browser's time zone, where the chart's day,
 * month, and year marks fall on UTC days (a limit of the library, `README.md`), so they read
 * by the UTC date they mark; a trade date by its own fields. */
export function tickMarkLabel(time: ChartTime, mark: TickMark): string {
  const instant =
    typeof time === "string"
      ? new Date(`${time}T00:00:00Z`)
      : new Date(time * 1000)
  const utcDate = instant.toISOString().slice(0, 10)
  if (mark === "year") {
    return utcDate.slice(0, 4)
  }
  if (mark === "month") {
    return utcDate.slice(0, 7)
  }
  if (mark === "day") {
    return utcDate.slice(5)
  }
  const clock = `${two(instant.getHours())}:${two(instant.getMinutes())}`
  return mark === "seconds" ? `${clock}:${two(instant.getSeconds())}` : clock
}

function isWholeSecond(time: number): time is UTCTimestamp {
  return Number.isInteger(time)
}

function localDate(instant: Date): string {
  return `${instant.getFullYear()}-${two(instant.getMonth() + 1)}-${two(instant.getDate())}`
}

function two(value: number): string {
  return String(value).padStart(2, "0")
}
