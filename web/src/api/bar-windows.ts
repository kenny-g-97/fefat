import { z } from "zod"
import type { components } from "./schema"

/** A page's bars as the API sends them, column by column. */
export type BarColumns = components["schemas"]["BarColumns"]

/** The trade dates a series' data holds (`GET /v1/market/bars/span`). */
export type HeldDates = components["schemas"]["HeldDates"]

/** A window of trade dates a series' bars are asked for, its first and its last, written as the
 * API writes a trade date: 2026-03-06. */
export type BarWindow = Readonly<{ from: string; to: string }>

/** The timeframes the chart offers: a minute to a day, built from any data held. */
export const timeframe = z.enum(["1m", "5m", "15m", "30m", "1h", "4h", "1d"])
export type Timeframe = z.infer<typeof timeframe>

const SECONDS_IN_A_DAY = 86_400
const MILLISECONDS_IN_A_DAY = SECONDS_IN_A_DAY * 1000
const SECONDS_IN: Readonly<Record<string, number>> = {
  m: 60,
  h: 3600,
  d: 86_400,
}
/** The most buckets of its timeframe a window spans, were every hour of every day traded: far
 * under the 20,000 bars a request may hold, and two or three pages of a session table's reading
 * at most (`fefat_app.services.market_bars`). */
export const BUCKETS_PER_WINDOW = 8_000
/** The most calendar days a window spans, about a year of daily bars. */
export const DAYS_PER_WINDOW = 366
const TRADE_DATE = /^(\d{4})-(\d{2})-(\d{2})$/

/** The seconds a bar of `chosen` spans: 300 for 5m. */
export function timeframeSeconds(chosen: Timeframe): number {
  const unit = SECONDS_IN[chosen.slice(-1)]
  if (unit === undefined) {
    throw new Error(
      `Expected a timeframe in minutes, hours, or days, got ${chosen}.`
    )
  }
  return Number(chosen.slice(0, -1)) * unit
}

/** The calendar days a window of `chosen` spans: as many as `BUCKETS_PER_WINDOW` buckets cover
 * on days traded around the clock, at least one and at most `DAYS_PER_WINDOW`. */
export function windowDays(chosen: Timeframe): number {
  const days = Math.floor(
    (BUCKETS_PER_WINDOW * timeframeSeconds(chosen)) / SECONDS_IN_A_DAY
  )
  return Math.min(DAYS_PER_WINDOW, Math.max(1, days))
}

/** The windows of `held`, newest first, on a grid of `windowDays` fixed from 1970-01-01, so that
 * a window keeps its dates, and so its cached bars, however far the chart has scrolled; the
 * newest and the oldest are cut to the dates held. */
export function barWindows(
  held: HeldDates,
  chosen: Timeframe
): readonly BarWindow[] {
  const days = windowDays(chosen)
  const first = dayNumber(held.first)
  const last = dayNumber(held.last)
  if (last < first) {
    throw new Error(
      `Expected held dates in order, got ${held.first} to ${held.last}.`
    )
  }
  const newest = Math.floor(last / days)
  const oldest = Math.floor(first / days)
  return Array.from({ length: newest - oldest + 1 }, (_, back) => {
    const index = newest - back
    return {
      from: tradeDate(Math.max(first, index * days)),
      to: tradeDate(Math.min(last, (index + 1) * days - 1)),
    }
  })
}

/** The bars of the windows loaded in a row from the newest, oldest first, as one set of
 * columns: `loaded` holds each window's bars, newest first, undefined from the first window not
 * loaded on. A window must end before the newer one begins. */
export function joinedBars(
  loaded: readonly (BarColumns | undefined)[]
): BarColumns {
  const run = loaded.findIndex((bars) => bars === undefined)
  const windows = (run === -1 ? loaded : loaded.slice(0, run))
    .filter((bars): bars is BarColumns => bars !== undefined)
    .toReversed()
  windows.forEach((bars, index) => {
    const newer = windows[index + 1]
    const last = bars.time.at(-1)
    const next = newer?.time.at(0)
    if (last !== undefined && next !== undefined && last >= next) {
      throw new Error(
        `Expected each window's bars before the next window's, got ${last} at or after ${next}.`
      )
    }
  })
  return {
    time: windows.flatMap((bars) => bars.time),
    trade_date: windows.flatMap((bars) => bars.trade_date),
    open: windows.flatMap((bars) => bars.open),
    high: windows.flatMap((bars) => bars.high),
    low: windows.flatMap((bars) => bars.low),
    close: windows.flatMap((bars) => bars.close),
    volume: windows.flatMap((bars) => bars.volume),
    contract: windows.flatMap((bars) => bars.contract),
  }
}

function dayNumber(date: string): number {
  const parts = TRADE_DATE.exec(date)
  if (parts === null) {
    throw new Error(
      `Expected a trade date such as 2026-03-06, got ${JSON.stringify(date)}.`
    )
  }
  const [, year, month, day] = parts
  return (
    Date.UTC(Number(year), Number(month) - 1, Number(day)) /
    MILLISECONDS_IN_A_DAY
  )
}

function tradeDate(day: number): string {
  return new Date(day * MILLISECONDS_IN_A_DAY).toISOString().slice(0, 10)
}
