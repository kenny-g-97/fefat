import type {
  BreaksSeen,
  FileSeen,
  ImportPreviewAnswer,
  MergeSeen,
} from "@/api/imports"
import type { components } from "@/api/schema"
import { counted, formatCount } from "@/ui/figures"
import type { FileState, Outcome } from "./import-reviews"

type Schemas = components["schemas"]

/** What a preview finds the import of a file or a batch would do, as its review's headline
 * says it, and Import's reason where the review shows one file or batch (D-105). */
export const VERDICTS: Readonly<Record<Schemas["ImportVerdict"], string>> = {
  imports: "It imports as it is",
  refused: "It would be refused",
  bars_in_breaks: "It would be refused for its bars in a break",
  differing: "Its records differ from the ones FEAT holds",
  imported_before: "It is imported already: importing it again changes nothing",
  nothing: "It holds nothing to import",
}

/** Each outcome in a word or two, as a file's row ends on it, and the Review step says one
 * file's (D-105). */
export const OUTCOME_NAMES: Readonly<Record<Outcome, string>> = {
  imports: "Imports",
  imports_without_bars: "Without bars in a break",
  refused: "Refused",
  bars_in_breaks: "Bars in a break",
  differing: "Differs",
  imported_before: "Imported before",
  nothing: "Nothing to import",
  unread: "Not read",
}

/** The sign colour an outcome takes (web/DESIGN.md, Palette; D-105): the positive for a file
 * that imports, as it is or without its bars in a break, the negative for one that something
 * stops, and neither for one imported before or empty, which is no error. */
export const OUTCOME_SIGNS: Readonly<
  Record<Outcome, "positive" | "negative" | "none">
> = {
  imports: "positive",
  imports_without_bars: "positive",
  refused: "negative",
  bars_in_breaks: "negative",
  differing: "negative",
  unread: "negative",
  imported_before: "none",
  nothing: "none",
}

/** What stops a file of a round from importing, on its row (D-105): why it was not read, its
 * first offset with what to check, its first problem, its bars in a break, or its records that
 * differ; none for a file that imports, was imported before, holds nothing, or is still read. */
export function whyNot(state: FileState, zone: string | null): string | null {
  switch (state.kind) {
    case "reading":
      return null
    case "failed":
      return state.error.message
    case "answered":
      return answerStops(state.answer, zone)
  }
}

function answerStops(
  answer: ImportPreviewAnswer,
  zone: string | null
): string | null {
  if (answer.kind === "refused") {
    return answer.message
  }
  if (answer.kind !== "file") {
    return `Expected a file's review, got a ${answer.kind} one.`
  }
  switch (answer.verdict) {
    case "imports":
    case "imported_before":
    case "nothing":
      return null
    case "refused":
      return refusalOf(answer, zone)
    case "bars_in_breaks":
      return answer.breaks_with_bars === null
        ? VERDICTS.bars_in_breaks
        : `${VERDICTS.bars_in_breaks}: ${barsLine(answer.breaks_with_bars)}`
    case "differing":
      return answer.merge === null
        ? VERDICTS.differing
        : `${VERDICTS.differing}: ${differingLine(answer.merge)}`
  }
}

/** A refused file's first refusal: an offset, with what to check, else a problem. */
function refusalOf(seen: FileSeen, zone: string | null): string {
  const [offset] = seen.offsets
  if (offset !== undefined) {
    return offsetLine(offset, zone)
  }
  const [problem] = seen.problems
  return problem === undefined ? VERDICTS.refused : problem
}

function differingLine(merge: MergeSeen): string {
  const records = counted(merge.records_differing, "record")
  return merge.differing_sessions.length === 0
    ? records
    : `${records} on ${listedDates(merge.differing_sessions, merge.differing_sessions_total)}`
}

/** An offset in words, with what to check, the time zone included where it points at one. */
export function offsetLine(
  offset: Schemas["OffsetSeen"],
  zone: string | null
): string {
  const dates =
    offset.first_trade_date === offset.last_trade_date
      ? `the trade date ${offset.first_trade_date}`
      : `the trade dates ${offset.first_trade_date} to ${offset.last_trade_date}`
  const read =
    zone === null
      ? "the time zone of the file's times"
      : `the time zone of the file's times, ${zone}`
  const check = {
    "time-zone": `check ${read}`,
    "bar-stamping":
      "check whether the file stamps each bar at its open or its close",
    "time-zone-or-bar-stamping": `check ${read}, and whether the file stamps each bar at its open or its close`,
  }[offset.cause]
  return `The records run ${offset.duration} ${offset.direction} against their calendar on ${dates}: ${check}.`
}

/** A file's bars in a break in counts: the bars, and the trade dates of the breaks they lie
 * in (ADR-0022). */
export function barsLine(breaks: BreaksSeen): string {
  const bars = counted(breaks.bars, "bar")
  const dates = listedDates(breaks.breaks, breaks.breaks_total)
  return breaks.breaks_total === 1
    ? `${bars} in the break after the trade date ${dates}`
    : `${bars} in ${formatCount(breaks.breaks_total)} breaks, after the trade dates ${dates}`
}

/** Trade dates as a list, with how many more past those the review lists. */
export function listedDates(dates: readonly string[], total: number): string {
  const more = total - dates.length
  return more > 0
    ? `${dates.join(", ")}, and ${formatCount(more)} more`
    : dates.join(", ")
}
