import type {
  RunEstimated,
  RunEstimateRequest,
  RunSubmission,
} from "@/api/runs"
import { counted } from "@/ui/figures"
import type { EnteredValues, ParameterValue } from "@/ui/schema-fields"

/** What the trader chose in the Run backtest dialog (web/DESIGN.md, Patterns, Run backtest
 * dialog); a choice left at null is the run's default, which the estimate names, the instrument
 * the one the code names, each side of the slippage on its own. Dates and ticks are texts as
 * typed, read once kept; `parameters` is null while a field is refused, and `entered` holds the
 * fields' texts for a dialog opened again. */
export type RunDraft = Readonly<{
  instrument: string | null
  provider: string | null
  contract: string | null
  fidelity: string | null
  feeTable: string | null
  slippage: Readonly<{ market: string | null; stop: string | null }>
  from: string | null
  to: string | null
  parameters: Readonly<Record<string, ParameterValue>> | null
  entered: EnteredValues
}>

/** A draft that asks for nothing but the run's defaults. */
export const UNTOUCHED: RunDraft = {
  instrument: null,
  provider: null,
  contract: null,
  fidelity: null,
  feeTable: null,
  slippage: { market: null, stop: null },
  from: null,
  to: null,
  parameters: {},
  entered: new Map(),
}

/** Whether the dialog can send its run, with the request; is reading the estimate of the latest
 * draft, which a press waits for; or waits on the trader, and why, in words. */
export type RunReadiness =
  | Readonly<{ kind: "ready"; request: RunSubmission }>
  | Readonly<{ kind: "reading" }>
  | Readonly<{ kind: "waiting"; why: string }>

/** The ticks of slippage a text can hold on each side. */
type TicksText = Readonly<{ market: string; stop: string }>

/** A window of trade dates, as the API writes them. */
type TradeDates = Readonly<{ start: string; end: string }>

const DATE_TEXT = /^(\d{4})-(\d{2})-(\d{2})$/
const WHOLE = /^\d+$/
const MOST_TICKS = 1_000

/** The days of `month` of `year`, from the calendar's rule rather than the browser's clock,
 * which would move a date near midnight. */
function daysIn(year: number, month: number): number {
  if (month === 2) {
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
    return leap ? 29 : 28
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31
}

/** Whether `text` is a date as the app writes one, `2026-03-06`, that the calendar holds. */
export function isTradeDate(text: string): boolean {
  const found = DATE_TEXT.exec(text)
  if (found === null) {
    return false
  }
  const [year, month, day] = [found[1], found[2], found[3]].map(Number)
  return month >= 1 && month <= 12 && day >= 1 && day <= daysIn(year, month)
}

/** Why `text` is no trade date of the data held from `held.start` to `held.end`, or null. Dates
 * are compared as the texts they are, which sort as dates, so that no browser's time zone moves
 * them a day. */
export function tradeDateRefusal(
  text: string,
  held: TradeDates
): string | null {
  if (!isTradeDate(text)) {
    return "Type a date such as 2026-03-06."
  }
  if (text < held.start || text > held.end) {
    return `Choose a date from ${held.start} to ${held.end}, the data this run reads.`
  }
  return null
}

/** Why a window from `from` to `to` cannot run, or null. */
export function windowRefusal(from: string, to: string): string | null {
  return to < from ? `Choose an end on or after ${from}.` : null
}

/** Why `text` is no number of ticks, or null. */
export function ticksRefusal(text: string): string | null {
  return WHOLE.test(text) && Number(text) <= MOST_TICKS
    ? null
    : "Type a whole number of ticks, such as 1."
}

/** What the estimate is asked of the draft: the choices that change what the run reads, each
 * date only once it is one, and neither of a window that ends before it starts, which its field
 * refuses and the server would too. */
export function estimateAsked(
  versionId: string,
  draft: RunDraft
): RunEstimateRequest {
  const from =
    draft.from !== null && isTradeDate(draft.from) ? draft.from : null
  const to = draft.to !== null && isTradeDate(draft.to) ? draft.to : null
  const backwards = from !== null && to !== null && to < from
  return {
    strategy_version_id: versionId,
    ...(from === null || backwards ? {} : { start: from }),
    ...(to === null || backwards ? {} : { end: to }),
    settings: {
      ...(draft.instrument === null ? {} : { instrument: draft.instrument }),
      ...(draft.provider === null ? {} : { provider: draft.provider }),
      ...(draft.contract === null ? {} : { contract: draft.contract }),
      ...(draft.fidelity === null ? {} : { fidelity: draft.fidelity }),
    },
  }
}

/** What the Instrument field offers, by name: the instruments the store holds, with the one the
 * code names and the one chosen, which it may not hold. */
export function instrumentChoices(
  held: readonly string[],
  own: string,
  chosen: string
): readonly string[] {
  return [...new Set([...held, own, chosen])].sort()
}

/** The draft once the run trades `chosen`, left out where it is the code's `own`. Another
 * instrument has its own providers, contracts, levels, and fees, so those go back to its
 * defaults; the dates and the ticks stay, a date refused where its data does not hold it. */
export function instrumentChosen(
  draft: RunDraft,
  chosen: string,
  own: string
): RunDraft {
  return {
    ...draft,
    instrument: chosen === own ? null : chosen,
    provider: null,
    contract: null,
    fidelity: null,
    feeTable: null,
  }
}

/** The fee table the run names: the one chosen, or the estimate's default where it prices the
 * instrument; null where none does, and a run could not be priced. */
export function feeTableOf(
  draft: RunDraft,
  estimate: RunEstimated
): string | null {
  const wanted =
    draft.feeTable === null ? estimate.settings.fee_table : draft.feeTable
  return estimate.fee_tables.some((choice) => choice.name === wanted)
    ? wanted
    : null
}

/** The dates the fields show: what was typed, or else the window the estimate read, or where it
 * met nothing, the dates the data holds; null where the data holds none. */
export function shownDates(
  draft: RunDraft,
  estimate: RunEstimated
): Readonly<{ from: string; to: string }> | null {
  if (estimate.held === null) {
    return null
  }
  const read = estimate.window === null ? estimate.held : estimate.window
  return {
    from: draft.from === null ? read.start : draft.from,
    to: draft.to === null ? read.end : draft.to,
  }
}

/** The ticks of slippage on each side: as typed, or else the run's default, which a change of
 * fidelity moves. */
export function shownTicks(draft: RunDraft, estimate: RunEstimated): TicksText {
  const { market, stop } = draft.slippage
  const applied = estimate.settings.slippage_ticks
  return {
    market: market === null ? String(applied.market) : market,
    stop: stop === null ? String(applied.stop) : stop,
  }
}

/** What a run would read: its sessions, then its bars and its ticks, leaving out the kind it
 * reads none of, since "0 bars" under a strategy of bars reads as an empty window. */
export function readWords({
  sessions,
  bars,
  ticks,
}: Pick<RunEstimated, "sessions" | "bars" | "ticks">): string {
  return [
    counted(sessions, "session"),
    ...(bars > 0 ? [counted(bars, "bar")] : []),
    ...(ticks > 0 ? [counted(ticks, "tick")] : []),
  ].join(", ")
}

/** The line beside Run: what the run would read, after what it trades where that is not what the
 * code names, `own`, since the choice outlives the dialog's closing. */
export function estimateWords(estimate: RunEstimated, own: string): string {
  const read = readWords(estimate)
  return estimate.instrument === own
    ? read
    : `Trades ${estimate.instrument}, not the code's ${own}: ${read}`
}

/** The Runs list's filter after a stress: the strategy, unless a run found saved stands under
 * another, or none, which that filter would hide. */
export function stressedSearch(
  runs: readonly Readonly<{ strategy: Readonly<{ name: string }> | null }>[],
  name: string
): Readonly<{ strategy?: string }> {
  return runs.every((run) => run.strategy?.name === name)
    ? { strategy: name }
    : {}
}

/** What the draft sends, once the estimate read for it holds a window with sessions, or why it
 * waits. A fidelity the data does not hold, chosen from another instrument's while its estimate
 * was read, waits: a run under it would fall back to a coarser level at that fidelity's slippage,
 * none on TBBO. */
export function runReadiness(
  versionId: string,
  draft: RunDraft,
  estimate: RunEstimated,
  latest: boolean
): RunReadiness {
  if (!latest) {
    return { kind: "reading" }
  }
  if (draft.fidelity !== null && !estimate.levels.includes(draft.fidelity)) {
    return { kind: "waiting", why: "Choose a fidelity the data holds" }
  }
  const window = windowOf(draft, estimate)
  if (window === null) {
    return { kind: "waiting", why: "Choose dates the data holds" }
  }
  if (estimate.sessions === 0) {
    return { kind: "waiting", why: "This window holds no data" }
  }
  const feeTable = feeTableOf(draft, estimate)
  if (feeTable === null) {
    return {
      kind: "waiting",
      why: `Choose commissions and fees that price ${estimate.instrument}`,
    }
  }
  const ticks = shownTicks(draft, estimate)
  if (
    ticksRefusal(ticks.market) !== null ||
    ticksRefusal(ticks.stop) !== null
  ) {
    return { kind: "waiting", why: "Type whole ticks of slippage" }
  }
  if (draft.parameters === null) {
    return { kind: "waiting", why: "Correct the parameter refused above" }
  }
  return {
    kind: "ready",
    request: {
      strategy_version_id: versionId,
      parameters: { ...draft.parameters },
      start: window.start,
      end: window.end,
      settings: settingsAsked(draft, estimate, feeTable, ticks),
    },
  }
}

/** The settings a run is sent with: those the dialog does not offer as the estimate applied
 * them, the instrument the estimate read, also the code's own, so that a parameter of the code
 * cannot trade another than the dialog shows, and the choices the trader made; slippage only
 * once a side of it is typed, so that the run's own default for its fidelity stands until then. */
function settingsAsked(
  draft: RunDraft,
  estimate: RunEstimated,
  feeTable: string,
  ticks: TicksText
): NonNullable<RunSubmission["settings"]> {
  const typed = draft.slippage.market !== null || draft.slippage.stop !== null
  return {
    latency_ms: estimate.settings.latency_ms,
    limit_fill: estimate.settings.limit_fill,
    roll_handling: estimate.settings.roll_handling,
    capital: estimate.settings.capital,
    replay: estimate.settings.replay,
    instrument: estimate.instrument,
    provider: estimate.settings.provider,
    fee_table: feeTable,
    ...(draft.contract === null ? {} : { contract: draft.contract }),
    ...(draft.fidelity === null ? {} : { fidelity: draft.fidelity }),
    ...(typed
      ? {
          slippage_ticks: {
            market: Number(ticks.market),
            stop: Number(ticks.stop),
          },
        }
      : {}),
  }
}

/** The window the draft asks for, each date left untouched being the estimate's; null while a
 * date typed is refused or the dates meet no data. */
function windowOf(draft: RunDraft, estimate: RunEstimated): TradeDates | null {
  const { held, window: read } = estimate
  if (held === null || read === null) {
    return null
  }
  const start = draft.from === null ? read.start : draft.from
  const end = draft.to === null ? read.end : draft.to
  if (
    tradeDateRefusal(start, held) !== null ||
    tradeDateRefusal(end, held) !== null ||
    windowRefusal(start, end) !== null
  ) {
    return null
  }
  return { start, end }
}
