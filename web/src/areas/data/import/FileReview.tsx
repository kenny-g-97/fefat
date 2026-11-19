import { cn } from "cn"
import type { Dispatch } from "react"
import type { BatchSeen, FileSeen } from "@/api/imports"
import { counted, formatCount } from "@/ui/figures"
import { datasetName } from "../datasets"
import { DisclosureRow } from "../DisclosureRow"
import type { Draft, DraftChange } from "./import-draft"
import { BarsChoice, BarsInBreaks } from "./BarsInBreaks"
import { Decision } from "./Decision"
import { FirstRecords } from "./FirstRecords"
import { correctsBars, differs, RECORDS_MESSAGE } from "./import-decisions"
import { filesOf } from "./import-request"
import { OUTCOME_SIGNS, offsetLine, VERDICTS } from "./import-outcomes"
import { Merge, RecordsChoice } from "./Merge"

/** A verdict's colour, its sign's (D-105): heading text where it is no error. */
const SIGN_TEXT = {
  positive: "text-positive",
  negative: "text-negative",
  none: "text-foreground",
} as const

type FileReviewProps = Readonly<{
  seen: FileSeen
  draft: Draft
  change: Dispatch<DraftChange>
  zone: string | null
  alone?: boolean
}>

/** What a file's import would do: the verdict, what was read and left out, each offset from
 * the calendar with what it points at and the time zone the file is read in, the problems, the
 * warnings, the calendar's check, the first records as stored, and what the file adds to the
 * data FEAT holds; where the file is reviewed `alone`, each box ends on its choice, the bars in
 * a break or the records that differ, while a round of several files asks them under its rows,
 * once for every file of a kind (D-106). */
export function FileReview({
  seen,
  draft,
  change,
  zone,
  alone = true,
}: FileReviewProps) {
  return (
    <div className="flex flex-col gap-4">
      <p
        data-testid="review-verdict"
        className={cn(
          alone ? "text-base font-semibold" : "font-medium",
          SIGN_TEXT[OUTCOME_SIGNS[seen.verdict]]
        )}
      >
        {verdictOf(seen)}
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
      {seen.breaks_with_bars !== null && (
        <BarsInBreaks breaks={seen.breaks_with_bars}>
          {alone && correctsBars(seen) && (
            <BarsChoice
              files={filesOf(draft.source)}
              records={seen.breaks_with_bars.records}
              draft={draft}
              change={change}
            />
          )}
        </BarsInBreaks>
      )}
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
          {alone && differs(seen) && (
            <div className="flex flex-col gap-3">
              <p className="text-foreground-secondary">
                {RECORDS_MESSAGE.file}
              </p>
              <RecordsChoice
                subject="file"
                files={filesOf(draft.source)}
                disputed={seen.merge.stored_records_disputed}
                draft={draft}
                change={change}
              />
            </div>
          )}
        </Merge>
      )}
    </div>
  )
}

/** What a Databento batch's import would do: the verdict, the batch's account in counts and
 * dates, what its files add to each dataset, and, where records differ in any, what to do with
 * them, for every dataset at once, in a box of its own under theirs (D-106), the stored records
 * that give way counted over all of them. */
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
        className={cn(
          "text-base font-semibold",
          SIGN_TEXT[OUTCOME_SIGNS[seen.verdict]]
        )}
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
        <Decision
          title="Records that differ"
          message={RECORDS_MESSAGE.batch}
          testId="batch-decision"
        >
          <RecordsChoice
            subject="batch"
            files={filesOf(draft.source)}
            disputed={disputed}
            draft={draft}
            change={change}
          />
        </Decision>
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

/** The verdict's words, a file that imports once its bars in a break are left out saying so. */
function verdictOf(seen: FileSeen): string {
  return seen.verdict === "imports" && seen.breaks_with_bars?.left_out === true
    ? "It imports without its bars in a break"
    : VERDICTS[seen.verdict]
}
