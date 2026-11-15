import type { ColumnMapping } from "@/api/imports"

/** What a column of a file holds for a profile (`ColumnMapping`), or nothing the import
 * reads: a bar's or a tick's, or what both have. */
export type Role =
  | "unused"
  | "timestamp"
  | "date"
  | "time"
  | "open"
  | "high"
  | "low"
  | "close"
  | "volume"
  | "trade_count"
  | "vwap"
  | "price"
  | "size"
  | "side"
  | "event_time"
  | "sequence"
  | "symbol"
  | "instrument_id"

/** A column as a profile names it: its header's name, or its place from 0 in a file without
 * a header row. */
export type ColumnKey = string | number

export const BAR_ROLES: readonly Role[] = [
  "unused",
  "timestamp",
  "date",
  "time",
  "open",
  "high",
  "low",
  "close",
  "volume",
  "trade_count",
  "vwap",
  "symbol",
  "instrument_id",
]

export const TICK_ROLES: readonly Role[] = [
  "unused",
  "timestamp",
  "date",
  "time",
  "price",
  "size",
  "side",
  "event_time",
  "sequence",
  "symbol",
  "instrument_id",
]

/** What each role's select says. */
export const ROLE_LABELS: Readonly<Record<Role, string>> = {
  unused: "Not read",
  timestamp: "Timestamp",
  date: "Date",
  time: "Time",
  open: "Open",
  high: "High",
  low: "Low",
  close: "Close",
  volume: "Volume",
  trade_count: "Trade count",
  vwap: "VWAP",
  price: "Price",
  size: "Size",
  side: "Side",
  event_time: "Event time",
  sequence: "Sequence",
  symbol: "Symbol",
  instrument_id: "Instrument id",
}

const BAR_NEEDS: readonly Role[] = ["open", "high", "low", "close", "volume"]
const TICK_NEEDS: readonly Role[] = ["price", "size"]
const TIMING: readonly Role[] = ["timestamp", "date", "time"]

/** Each column's role in `mapping`, `keys` naming the file's columns in order: a column the
 * mapping does not name is not read. */
export function rolesOf(
  mapping: ColumnMapping,
  keys: readonly ColumnKey[]
): readonly Role[] {
  const named = new Map<ColumnKey, Role>(
    mappedRoles(mapping).map(([role, key]) => [key, role])
  )
  return keys.map((key) => named.get(key) ?? "unused")
}

/** `roles` with the column at `index` taking `role`: one role a column and one column a role,
 * so that a role taken from another column leaves it unread, and a timestamp in one column and
 * a date and a time in two never stand together. */
export function withRole(
  roles: readonly Role[],
  index: number,
  role: Role
): readonly Role[] {
  const apart = role === "timestamp" ? ["date", "time"] : ["timestamp"]
  const clears = (held: Role) =>
    role !== "unused" &&
    (held === role || (TIMING.includes(role) && apart.includes(held)))
  return roles.map((held, at) =>
    at === index ? role : clears(held) ? "unused" : held
  )
}

/** The profile's columns of `roles`, or the roles still to choose: a timestamp, or a date and
 * a time, then a bar's prices and volume, or a tick's price and size; the record type the
 * profile had stays. */
export type Mapped =
  | Readonly<{ kind: "mapped"; mapping: ColumnMapping }>
  | Readonly<{ kind: "missing"; roles: readonly Role[] }>

export function mappingOf(
  roles: readonly Role[],
  keys: readonly ColumnKey[],
  ticks: boolean,
  kept: ColumnMapping
): Mapped {
  const keyOf = (role: Role): ColumnKey | null => {
    const index = roles.indexOf(role)
    const key = keys[index]
    return index === -1 || key === undefined ? null : key
  }
  const needs = ticks ? TICK_NEEDS : BAR_NEEDS
  const timed =
    keyOf("timestamp") !== null ||
    (keyOf("date") !== null && keyOf("time") !== null)
  const missing = [
    ...(timed ? [] : (["timestamp"] satisfies Role[])),
    ...needs.filter((role) => keyOf(role) === null),
  ]
  if (missing.length > 0) {
    return { kind: "missing", roles: missing }
  }
  const shared = {
    timestamp: keyOf("timestamp"),
    date: keyOf("date"),
    time: keyOf("time"),
    symbol: keyOf("symbol"),
    instrument_id: keyOf("instrument_id"),
    record_type: kept.record_type ?? null,
  }
  return {
    kind: "mapped",
    mapping: ticks
      ? { ...shared, ticks: tickColumns(keyOf) }
      : { ...shared, bars: barColumns(keyOf) },
  }
}

type KeyOf = (role: Role) => ColumnKey | null

function barColumns(keyOf: KeyOf): NonNullable<ColumnMapping["bars"]> {
  return {
    open: required(keyOf, "open"),
    high: required(keyOf, "high"),
    low: required(keyOf, "low"),
    close: required(keyOf, "close"),
    volume: required(keyOf, "volume"),
    trade_count: keyOf("trade_count"),
    vwap: keyOf("vwap"),
  }
}

function tickColumns(keyOf: KeyOf): NonNullable<ColumnMapping["ticks"]> {
  return {
    price: required(keyOf, "price"),
    size: required(keyOf, "size"),
    side: keyOf("side"),
    event_time: keyOf("event_time"),
    sequence: keyOf("sequence"),
  }
}

function required(keyOf: KeyOf, role: Role): ColumnKey {
  const key = keyOf(role)
  if (key === null) {
    throw new Error(`Expected a column for the ${role}, got none.`)
  }
  return key
}

/** Each role `mapping` gives a column, with the column. */
function mappedRoles(
  mapping: ColumnMapping
): readonly (readonly [Role, ColumnKey])[] {
  const roles: readonly (readonly [Role, ColumnKey | null | undefined])[] = [
    ["timestamp", mapping.timestamp],
    ["date", mapping.date],
    ["time", mapping.time],
    ["symbol", mapping.symbol],
    ["instrument_id", mapping.instrument_id],
    ["open", mapping.bars?.open],
    ["high", mapping.bars?.high],
    ["low", mapping.bars?.low],
    ["close", mapping.bars?.close],
    ["volume", mapping.bars?.volume],
    ["trade_count", mapping.bars?.trade_count],
    ["vwap", mapping.bars?.vwap],
    ["price", mapping.ticks?.price],
    ["size", mapping.ticks?.size],
    ["side", mapping.ticks?.side],
    ["event_time", mapping.ticks?.event_time],
    ["sequence", mapping.ticks?.sequence],
  ]
  return roles.flatMap(([role, key]) => {
    if (key === null || key === undefined) {
      return []
    }
    const named: readonly [Role, ColumnKey] = [role, key]
    return [named]
  })
}
