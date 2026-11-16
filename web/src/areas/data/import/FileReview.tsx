import type { Dispatch } from "react"
import type { BatchSeen, FileSeen } from "@/api/imports"
import type { components } from "@/api/schema"
import { counted, formatCount } from "@/ui/figures"
import { datasetName } from "../datasets"
import { DisclosureRow } from "../DisclosureRow"
import type { Draft, DraftChange } from "./import-draft"
import { FirstRecords } from "./FirstRecords"
import { Merge, TakeRecords } from "./Merge"

type Schemas = components["schemas"]

/** What a preview finds the import would do, as its headline says it. */
const VERDICTS: Readonly<Record<Schemas["ImportVerdict"], string>> = {
  imports: "It imports as it is",
  refused: "It would be refused",
  differing: "Its records differ from the ones FEAT holds",
  imported_before: "It is imported already: importing it again changes nothing",
  nothing: "It holds nothing to import",
}

type FileReviewProps = Readonly<{
  seen: FileSeen
  draft: Draft
  change: Dispatch<DraftChange>
  zone: string | null
}>

/** What a file's import would do: the verdict, what was read and left out, each offset from
 * the calendar with what it points at and the time zone the file is read in, the problems, the
 * warnings, the calendar's check, the first records as stored, and what the file adds to the
 * data FEAT holds. */
export function FileReview({ seen, draft, change, zone }: FileReviewProps) {
  return (
    <div className="flex flex-col gap-4">
      <p
        data-testid="review-verdict"
        className="text-base font-semibold text-foreground"
      >
        {VERDICTS[seen.verdict]}
      </p>
      <p className="text-foreground-secondary">{readingLine(seen)}</p>
      {seen.offsets.map((offset) => (
        <p
          key={`${offset.first_trade_date} ${offset.cause}`}
          data-testid="review-offset"
          className="text-negative"
        >
          {offsetLine(offset, zone)}
        </p>
      ))}
      <Listed
        title="Problems"
        lines={seen.problems}
        total={seen.problems_total}
        negative
      />
      <Listed
        title="Warnings"
        lines={seen.warnings}
        total={seen.warnings.length}
      />
      <CalendarCheck seen={seen} />
      <FirstRecords records={seen.first_records} />
      {seen.merge !== null && (
        <Merge merge={seen.merge}>
          {seen.merge.records_differing > 0 && (
            <TakeRecords
              disputed={seen.merge.stored_records_disputed}
              draft={draft}
              change={change}
            />
          )}
        </Merge>
      )}
    </div>
  )
}

/** What a Databento batch's import would do: the verdict, the batch's account in counts and
 * dates, what its files add to each dataset, and, where records differ in any, what to do with
 * them, for every dataset at once, the stored records that give way counted over all of them. */
export function BatchReview({
  seen,
  draft,
  change,
}: Readonly<{ seen: BatchSeen; draft: Draft; change: Dispatch<DraftChange> }>) {
  const differing = seen.merges.some((merge) => merge.records_differing > 0)
  const disputed = seen.merges.reduce(
    (total, merge) => total + merge.stored_records_disputed,
    0
  )
  return (
    <div className="flex flex-col gap-4">
      <p
        data-testid="review-verdict"
        className="text-base font-semibold text-foreground"
      >
        {VERDICTS[seen.verdict]}
      </p>
      <pre className="overflow-x-auto rounded-xl border bg-muted p-4 text-xs text-foreground-secondary">
        {seen.lines.join("\n")}
      </pre>
      {seen.merges.map((merge) => (
        <Merge key={datasetName(merge.dataset)} merge={merge} />
      ))}
      {differing && (
        <TakeRecords disputed={disputed} draft={draft} change={change} />
      )}
    </div>
  )
}

/** The calendar's check of the file's sessions, its mismatches folded under it, since a file
 * read in the wrong time zone has one on nearly every trade date. */
function CalendarCheck({ seen }: Readonly<{ seen: FileSeen }>) {
  const checked = `${counted(seen.days_checked, "trade date")} checked`
  if (seen.mismatches.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">{`Calendar check: ${checked}, no mismatch.`}</p>
    )
  }
  const more = seen.mismatches_total - seen.mismatches.length
  return (
    <div>
      <DisclosureRow
        testId="review-mismatches"
        name="Calendar check"
        note={`${checked}, ${counted(seen.mismatches_total, "mismatch", "mismatches")}`}
      >
        <ul className="flex flex-col gap-1 pb-3 text-xs text-foreground-secondary">
          {seen.mismatches.map((line) => (
            <li key={line}>{line}</li>
          ))}
          {more > 0 && <li>{`And ${formatCount(more)} more`}</li>}
        </ul>
      </DisclosureRow>
    </div>
  )
}

type ListedProps = Readonly<{
  title: string
  lines: readonly string[]
  total: number
  negative?: boolean
}>

function Listed({ title, lines, total, negative = false }: ListedProps) {
  if (lines.length === 0) {
    return null
  }
  const more = total - lines.length
  return (
    <div className="flex flex-col gap-1">
      <p className="font-medium text-foreground">{title}</p>
      <ul
        className={
          negative
            ? "flex flex-col gap-1 text-negative"
            : "flex flex-col gap-1 text-foreground-secondary"
        }
      >
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
        {more > 0 && <li>{`And ${formatCount(more)} more`}</li>}
      </ul>
    </div>
  )
}

function readingLine(seen: FileSeen): string {
  const contracts =
    seen.contracts_total > seen.contracts.length
      ? `${seen.contracts.join(", ")}, and ${formatCount(seen.contracts_total - seen.contracts.length)} more`
      : seen.contracts.join(", ")
  const dates =
    seen.first_trade_date === null
      ? "no trade date"
      : `trade dates ${seen.first_trade_date} to ${seen.last_trade_date}`
  const leftOut = [
    seen.bars_without_volume > 0
      ? `${counted(seen.bars_without_volume, "bar")} without volume`
      : "",
    seen.spread_rows > 0
      ? `${counted(seen.spread_rows, "row")} of spreads`
      : "",
  ].filter((part) => part !== "")
  const read = `${counted(seen.rows_read, "row")} of ${seen.file_name} read with ${seen.profile} into ${counted(seen.records, "record")} of ${datasetName(seen.dataset)}: ${contracts === "" ? "no contract" : contracts}, ${dates}.`
  return leftOut.length === 0
    ? read
    : `${read} Left out: ${leftOut.join(" and ")}.`
}

/** An offset in words, with what to check, the time zone included where it points at one. */
function offsetLine(
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
