import { type ReactNode, useState } from "react"
import { fidelityLabel, sentenceCase } from "@/ui/figures"
import { KeptField } from "@/ui/kept-field"
import { Choice, Picker } from "@/ui/picker"
import { isTradeDate } from "@/ui/trade-date"
import { FILL_ROLES, PNL_SIGNS, type TradesSearch } from "./run-search"

/** The selects' first choice, which asks nothing of its column; no word of the API holds
 * parentheses. */
const ALL = "(all)"
const SIGN_WORDS = {
  positive: "Winning",
  negative: "Losing",
  zero: "Breakeven",
} as const
const SIDES = [
  { value: "long", label: "Long" },
  { value: "short", label: "Short" },
] as const
const FLAGS = [
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
] as const

/** A change to what the table asks, kept in the page's address. */
export type TradesAsked = Partial<Omit<TradesSearch, "key" | "tab">>

type TradesToolbarProps = Readonly<{
  search: TradesSearch
  exitReasons: readonly string[]
  fidelities: readonly string[]
  onAsk: (change: TradesAsked) => void
  chooser: ReactNode
}>

/** The fields over the trade table that narrow its trades (web/DESIGN.md, Patterns, List
 * filters), in the order of the columns they filter, on two lines: the trade dates of the
 * entry, the side, and the sign of the net P&L, then the exit reason, the fidelity of the
 * entry's fill, and an ambiguous fill on the trade's path, with the column chooser at the
 * second line's end; each kept in the page's address. The exit reasons and fidelities offered
 * are those the run's breakdowns count. */
export function TradesToolbar({
  search,
  exitReasons,
  fidelities,
  onAsk,
  chooser,
}: TradesToolbarProps) {
  return (
    <div
      role="group"
      aria-label="Filter trades"
      className="flex flex-col gap-4"
    >
      <div className="flex flex-wrap items-start gap-4">
        <DateRange start={search.start} end={search.end} onAsk={onAsk} />
        <Choice id="trades-side" label="Side">
          <Picker
            id="trades-side"
            className="w-30"
            value={search.side ?? ALL}
            options={[{ value: ALL, label: "All" }, ...SIDES]}
            onChange={(chosen) =>
              onAsk({
                side: SIDES.find((side) => side.value === chosen)?.value,
              })
            }
          />
        </Choice>
        <Choice id="trades-pnl" label="P&L">
          <Picker
            id="trades-pnl"
            className="w-36"
            value={search.pnl_sign ?? ALL}
            options={[
              { value: ALL, label: "All" },
              ...PNL_SIGNS.map((sign) => ({
                value: sign,
                label: SIGN_WORDS[sign],
              })),
            ]}
            onChange={(chosen) =>
              onAsk({ pnl_sign: PNL_SIGNS.find((sign) => sign === chosen) })
            }
          />
        </Choice>
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <Choice id="trades-exit" label="Exit reason">
          <Picker
            id="trades-exit"
            className="w-56"
            value={search.exit_reason ?? ALL}
            options={[
              { value: ALL, label: "All" },
              ...exitReasons.map((reason) => ({
                value: reason,
                label: sentenceCase(reason),
              })),
            ]}
            onChange={(chosen) =>
              onAsk({
                exit_reason: FILL_ROLES.find((role) => role === chosen),
              })
            }
          />
        </Choice>
        <Choice id="trades-fidelity" label="Fidelity">
          <Picker
            id="trades-fidelity"
            className="w-44"
            value={search.fidelity ?? ALL}
            options={[
              { value: ALL, label: "All" },
              ...fidelities.map((fidelity) => ({
                value: fidelity,
                label: fidelityLabel(fidelity),
              })),
            ]}
            onChange={(chosen) =>
              onAsk({ fidelity: chosen === ALL ? undefined : chosen })
            }
          />
        </Choice>
        <Choice id="trades-ambiguous" label="Ambiguous">
          <Picker
            id="trades-ambiguous"
            className="w-28"
            value={
              search.ambiguous === undefined ? ALL : String(search.ambiguous)
            }
            options={[{ value: ALL, label: "All" }, ...FLAGS]}
            onChange={(chosen) =>
              onAsk({
                ambiguous: chosen === ALL ? undefined : chosen === "true",
              })
            }
          />
        </Choice>
        <div className="ml-auto">{chooser}</div>
      </div>
    </div>
  )
}

/** The id of the From field, which Clear filters sends the focus to. */
export const FROM_FIELD = "trades-start"

type Dates = Readonly<{ start: string | undefined; end: string | undefined }>
type DateEnd = keyof Dates
/** The text each end's field holds that it refused, which the address does not hold. */
type RefusedDates = Readonly<{ start: string | null; end: string | null }>

const NONE_REFUSED: RefusedDates = { start: null, end: null }

/** From and To, the trade dates of the entry, each checked against the other end as last kept
 * here, which the page's address may not hold yet, so that a date typed straight after the
 * other is checked against it. A refused date stays in its field under its reason until it is
 * kept again, and is kept with the other end once that end admits it, so that no field shows a
 * date the table does not apply; a change of the address from elsewhere, as a reload, replaces
 * what is kept. */
function DateRange({
  start,
  end,
  onAsk,
}: Dates & Readonly<{ onAsk: (change: TradesAsked) => void }>) {
  const [kept, setKept] = useState<Dates>({ start, end })
  const [refused, setRefused] = useState<RefusedDates>(NONE_REFUSED)
  const [given, setGiven] = useState<Dates>({ start, end })
  if (given.start !== start || given.end !== end) {
    setGiven({ start, end })
    setKept({ start, end })
  }
  const keep = (at: DateEnd, typed: string) => {
    const text = typed.trim()
    if (dateRefusal(at, text, kept) !== null) {
      setRefused(withEnd(refused, at, text))
      return
    }
    const other = at === "start" ? "end" : "start"
    const accepted = withEnd(kept, at, dateOf(text))
    const waiting = refused[other]
    const admitted =
      waiting !== null && dateRefusal(other, waiting, accepted) === null
    const next = admitted ? withEnd(accepted, other, dateOf(waiting)) : accepted
    setKept(next)
    setRefused(admitted ? NONE_REFUSED : withEnd(refused, at, null))
    onAsk(next)
  }
  const fieldOf = (at: DateEnd) => {
    const typed = refused[at]
    const date = kept[at]
    return {
      text: typed !== null ? typed : date === undefined ? "" : date,
      refusal: typed === null ? null : dateRefusal(at, typed, kept),
      onKeep: (text: string) => keep(at, text),
    }
  }
  return (
    <>
      <DateField id={FROM_FIELD} label="From" {...fieldOf("start")} />
      <DateField id="trades-end" label="To" {...fieldOf("end")} />
    </>
  )
}

/** Why `text`, typed for the end `at` of the range `kept`, is no trade date of it: no date the
 * calendar holds, or out of order with the other end; null for a date, or none. */
function dateRefusal(at: DateEnd, text: string, kept: Dates): string | null {
  if (text === "") {
    return null
  }
  if (!isTradeDate(text)) {
    return "Type a date such as 2026-03-05."
  }
  if (at === "start") {
    return kept.end !== undefined && text > kept.end
      ? "Type a date on or before To."
      : null
  }
  return kept.start !== undefined && text < kept.start
    ? "Type a date on or after From."
    : null
}

function dateOf(text: string): string | undefined {
  return text === "" ? undefined : text
}

function withEnd<T>(
  dates: Readonly<{ start: T; end: T }>,
  at: DateEnd,
  value: T
): Readonly<{ start: T; end: T }> {
  return at === "start" ? { ...dates, start: value } : { ...dates, end: value }
}

type DateFieldProps = Readonly<{
  id: string
  label: string
  text: string
  refusal: string | null
  onKeep: (typed: string) => void
}>

/** A trade date typed as the app writes one, kept once left or on Enter (`KeptField`), empty
 * for every date, its refusal, if any, under it. */
function DateField({ id, label, text, refusal, onKeep }: DateFieldProps) {
  return (
    <Choice id={id} label={label} refusal={refusal} className="w-36">
      <KeptField
        id={id}
        value={text}
        placeholder="Any date"
        invalid={refusal !== null}
        describedBy={refusal === null ? undefined : `${id}-refusal`}
        onKeep={onKeep}
      />
    </Choice>
  )
}
