import { type Dispatch, type ReactNode, useState } from "react"
import type { BreaksSeen } from "@/api/imports"
import { Button } from "@/ui/button"
import { counted, formatCount } from "@/ui/figures"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import type { Draft, DraftChange } from "./import-draft"
import { barsLine, listedDates } from "./import-outcomes"

type BarsInBreaksProps = Readonly<{ breaks: BreaksSeen; children?: ReactNode }>

/** A file's breaks that hold a bar closing at the next session's open, the edge of a stretch
 * the platform stamped early (ADR-0022), in a box in the card as the merge's (web/DESIGN.md,
 * Patterns, Review), each line a label and its counts: the bars and the trade dates of the
 * breaks they lie in, the sessions beside them, the sessions ending a bar early that go with
 * them where there are any (D-104), and the records leaving them out leaves out; at its foot,
 * where the review shows one file, what to do with them (`LeaveOutBars`). */
export function BarsInBreaks({ breaks, children }: BarsInBreaksProps) {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border bg-muted p-4"
      data-testid="breaks-account"
    >
      <p className="font-medium text-foreground">Bars in a break</p>
      <ul className="flex flex-col gap-1 text-foreground-secondary">
        <li>{`Breaks: ${barsLine(breaks)}`}</li>
        <li>{`Sessions beside: ${listedDates(breaks.sessions, breaks.sessions_total)}`}</li>
        {breaks.ending_a_bar_early_total > 0 && (
          <li>
            {`Sessions ending a bar early: ${listedDates(breaks.ending_a_bar_early, breaks.ending_a_bar_early_total)}`}
          </li>
        )}
        <li>{`Records: ${formatCount(breaks.records)} in all, those bars among them`}</li>
      </ul>
      {children}
    </div>
  )
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
 * sessions; once approved for every one of `files`, what is left out and the way back, which
 * takes the focus from the confirm it replaces and, pressed, gives it to the trigger again. The
 * trigger starts its own line, so that Keep takes its place, as Take the file's records does. */
export function LeaveOutBars({
  files,
  records,
  draft,
  change,
}: LeaveOutBarsProps) {
  const [takenBack, setTakenBack] = useState(false)
  const offered = files.filter((file) => !draft.breaksLeftOut.includes(file))
  if (offered.length === 0) {
    return (
      <div className="flex flex-col items-start gap-3" data-testid="leave-out">
        <p className="text-foreground-secondary">
          {records === null
            ? `The bars in a break of ${counted(files.length, "file")} and the sessions their rows list are left out of the import, so each file's calendar check may list those sessions as having no prints.`
            : "These bars and the sessions above are left out of the import, so the calendar check may list those sessions as having no prints."}
        </p>
        <Button
          variant="ghost"
          size="sm"
          autoFocus
          onClick={() => {
            setTakenBack(true)
            change({
              kind: "bars in breaks",
              files: draft.breaksLeftOut.filter(
                (file) => !files.includes(file)
              ),
            })
          }}
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
          ? "Where a file's break holds a bar closing at the next session's open, the platform stamped that stretch early, and its own chart draws it so too. Compare those sessions with another source's bars: leaving them out imports the rest of each file, and keeping them keeps those files out."
          : "A bar closing at the next session's open marks a stretch the platform stamped early, and its own chart draws it so too. Compare these sessions with another source's bars: leaving them out imports the rest of the file, and keeping them keeps the file out."}
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
        focused={takenBack}
        onConfirm={() => {
          setTakenBack(false)
          change({
            kind: "bars in breaks",
            files: [...draft.breaksLeftOut, ...offered],
          })
        }}
      />
    </div>
  )
}
