import type { Dispatch, ReactNode } from "react"
import type { BreaksSeen } from "@/api/imports"
import { Button } from "@/ui/button"
import { counted, formatCount } from "@/ui/figures"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import type { Draft, DraftChange } from "./import-draft"

type BarsInBreaksProps = Readonly<{ breaks: BreaksSeen; children?: ReactNode }>

/** A file's breaks that hold a bar closing at the next session's open, the edge of a stretch
 * the platform stamped early (ADR-0022), in a box in the card as the merge's (web/DESIGN.md,
 * Patterns, Review): the bars and the trade dates of the breaks they lie in, and the sessions
 * beside them with their records, which leaving them out leaves out; at its foot, where the
 * review shows one file, what to do with them (`LeaveOutBars`). */
export function BarsInBreaks({ breaks, children }: BarsInBreaksProps) {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border bg-muted p-4"
      data-testid="breaks-account"
    >
      <p className="font-medium text-foreground">Bars in a break</p>
      <ul className="flex flex-col gap-1 text-foreground-secondary">
        <li>{breaksLine(breaks)}</li>
        <li>
          {`Sessions beside: ${listed(breaks.sessions, breaks.sessions_total)}, ${counted(breaks.records, "record")} in all`}
        </li>
      </ul>
      {children}
    </div>
  )
}

function breaksLine(breaks: BreaksSeen): string {
  const bars = counted(breaks.bars, "bar")
  const dates = listed(breaks.breaks, breaks.breaks_total)
  return breaks.breaks_total === 1
    ? `Breaks: ${bars} in the break after the trade date ${dates}`
    : `Breaks: ${bars} in ${formatCount(breaks.breaks_total)} breaks, after the trade dates ${dates}`
}

function listed(dates: readonly string[], total: number): string {
  const more = total - dates.length
  return more > 0
    ? `${dates.join(", ")}, and ${formatCount(more)} more`
    : dates.join(", ")
}

type LeaveOutBarsProps = Readonly<{
  files: readonly string[]
  records: number | null
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** Where bars in a break refuse a file (ADR-0022): what they mean and what to check first, then
 * Leave out the bars in a break behind an inline confirmation that counts the records that go,
 * `records`, or for several files (D-102) the files, since two files of one contract share
 * sessions; once approved for every one of `files`, what is left out and the way back. The
 * trigger starts its own line, so that Keep takes its place, as Take the file's records does. */
export function LeaveOutBars({
  files,
  records,
  draft,
  change,
}: LeaveOutBarsProps) {
  const offered = files.filter((file) => !draft.breaksLeftOut.includes(file))
  if (offered.length === 0) {
    return (
      <div className="flex flex-col items-start gap-3" data-testid="leave-out">
        <p className="text-foreground-secondary">
          {records === null
            ? `The bars in a break of ${counted(files.length, "file")} and the sessions beside them are left out of the import; each file's row says which.`
            : `These bars and the sessions beside them are left out of the import, ${counted(records, "record")} in all.`}
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            change({
              kind: "bars in breaks",
              files: draft.breaksLeftOut.filter(
                (file) => !files.includes(file)
              ),
            })
          }
        >
          Leave nothing out
        </Button>
      </div>
    )
  }
  return (
    <div className="flex flex-col items-start gap-3" data-testid="leave-out">
      <p className="text-foreground-secondary">
        {records === null
          ? "Where a file's break holds a bar closing at the next session's open, the platform stamped that stretch early. Compare those sessions with the platform's chart; where they are wrong, leave them out, and the rest of each file imports."
          : "A bar closing at the next session's open marks a stretch the platform stamped early. Compare these sessions with the platform's chart; where they are wrong, leave them out, and the rest of the file imports."}
      </p>
      <InlineConfirmation
        trigger={
          records === null
            ? "Leave out the files' bars in a break"
            : "Leave out the bars in a break"
        }
        confirm={
          records === null
            ? `Leave them out of ${counted(offered.length, "file")}`
            : `Leave out ${counted(records, "record")}`
        }
        align="start"
        onConfirm={() =>
          change({
            kind: "bars in breaks",
            files: [...draft.breaksLeftOut, ...offered],
          })
        }
      />
    </div>
  )
}
