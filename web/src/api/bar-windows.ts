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
  s: 1,
  m: 60,
  h: 3600,
  d: 86_400,
}
const BAR_LENGTH = /^(\d+)([smhd])$/
/** The most buckets of its timeframe a window spans, were every hour of every day traded: far
 * under the 20,000 bars a request may hold, and two or three pages of a session table's reading
 * at most (`fefat_app.services.market_bars`). */
export const BUCKETS_PER_WINDOW = 8_000
/** The most calendar days a window spans, about a year of daily bars. */
export const DAYS_PER_WINDOW = 366
const TRADE_DATE = /^(\d{4})-(\d{2})-(\d{2})$/

/** The seconds a bar `length` long spans, as a timeframe or a dataset's fidelity writes it: 300
 * for 5m. */
export function barSeconds(length: string): number {
  const parts = BAR_LENGTH.exec(length)
  const unit = parts === null ? undefined : SECONDS_IN[parts[2]]
  if (parts === null || unit === undefined) {
    throw new Error(
      `Expected a bar length such as 5m, got ${JSON.stringify(length)}.`
    )
  }
  return Number(parts[1]) * unit
}

/** The calendar days a window of bars `chosen` long spans, a timeframe such as `5m`: as many as
 * `BUCKETS_PER_WINDOW` buckets cover on days traded around the clock, at least one and at most
 * `DAYS_PER_WINDOW`. */
export function windowDays(chosen: string): number {
  const days = Math.floor(
    (BUCKETS_PER_WINDOW * barSeconds(chosen)) / SECONDS_IN_A_DAY
  )
  return Math.min(DAYS_PER_WINDOW, Math.max(1, days))
}

/** The windows of `held`, newest first, on a grid of `windowDays` fixed from 1970-01-01, so that
 * a window keeps its dates, and so its cached bars, however far the chart has scrolled; the
 * newest and the oldest are cut to the dates held. A run's chart cuts its own on the
 * strategy's timeframe, any bar length (step 5.9). */
export function barWindows(
  held: HeldDates,
  chosen: string
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

/** A run of windows of `barWindows`, by their indexes, the newest window 0: from `newest` to
 * `oldest`, both among them. */
export type WindowRange = Readonly<{ newest: number; oldest: number }>

/** The index of the window of `windows`, newest first, whose dates hold `date`, a trade date
 * such as 2026-03-06; the nearest where none does, the newest past them and the oldest before
 * them. */
export function windowAt(windows: readonly BarWindow[], date: string): number {
  const holding = windows.findIndex((each) => each.from <= date)
  return holding === -1 ? windows.length - 1 : holding
}

/** How many bars short of either end of those loaded the next window is asked for. */
const GROWS_WITHIN = 500

/** `range` one window older where fewer than 500 bars lie before the view, and one newer where
 * fewer than 500 lie after it, within the `count` windows there are; `range` itself where
 * neither, so that a caller sets no new state. */
export function grownRange(
  range: WindowRange,
  visible: Readonly<{ before: number; after: number }>,
  count: number
): WindowRange {
  const oldest =
    visible.before < GROWS_WITHIN
      ? Math.min(count - 1, range.oldest + 1)
      : range.oldest
  const newest =
    visible.after < GROWS_WITHIN ? Math.max(0, range.newest - 1) : range.newest
  return oldest === range.oldest && newest === range.newest
    ? range
    : { newest, oldest }
}

/** The run of `loaded`, a value of each window asked for in order, undefined for one not read
 * yet, that holds the window `at` and reads in a row both ways from it; none while `at` is not
 * read. */
export function readAround<T>(
  loaded: readonly (T | undefined)[],
  at: number
): Readonly<{ from: number; to: number }> | null {
  if (at < 0 || loaded[at] === undefined) {
    return null
  }
  let from = at
  while (from > 0 && loaded[from - 1] !== undefined) {
    from -= 1
  }
  let to = at
  while (to < loaded.length - 1 && loaded[to + 1] !== undefined) {
    to += 1
  }
  return { from, to }
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

/** The bars up to the last that traded. `load` keeps a contract that stopped trading on the
 * session grid, flat at its last close and without volume up to the session's close, and the
 * chart ends at its last trade; the rows without volume between two trades stay. The bars come
 * back as they are when the last one traded, or when none did. */
export function tradedBars(bars: BarColumns): BarColumns {
  const end = bars.volume.findLastIndex((volume) => volume > 0) + 1
  if (end === 0 || end === bars.volume.length) {
    return bars
  }
  return {
    time: bars.time.slice(0, end),
    trade_date: bars.trade_date.slice(0, end),
    open: bars.open.slice(0, end),
    high: bars.high.slice(0, end),
    low: bars.low.slice(0, end),
    close: bars.close.slice(0, end),
    volume: bars.volume.slice(0, end),
    contract: bars.contract.slice(0, end),
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
