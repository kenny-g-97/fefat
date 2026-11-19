import type { Dispatch, ReactNode } from "react"
import type { BreaksSeen } from "@/api/imports"
import { counted, formatCount } from "@/ui/figures"
import { Options } from "./Decision"
import { allCorrected, BARS_MESSAGE } from "./import-decisions"
import type { Draft, DraftChange } from "./import-draft"
import { barsLine, listedDates } from "./import-outcomes"

type BarsInBreaksProps = Readonly<{ breaks: BreaksSeen; children?: ReactNode }>

/** A file's breaks that hold a bar closing at the next session's open, the edge of a stretch
 * the platform stamped early (ADR-0022), in a box in the card as the merge's (web/DESIGN.md,
 * Patterns, Review), each line a label and its counts: the bars and the trade dates of the
 * breaks they lie in, the sessions beside them, the sessions ending a bar early that go with
 * them where there are any (D-104), and the records leaving them out leaves out; at its foot,
 * where the review shows one file, what to do with them (`BarsChoice`). */
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

type BarsChoiceProps = Readonly<{
  files: readonly string[]
  records: number
  current: boolean
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** Where bars in a break refuse the one file the review shows (ADR-0022; D-106): what they mean
 * and what to check, then the choice, the file imported without them, which counts the
 * `records` that go, or not imported, chosen at the start, since it is what happens if nothing
 * is chosen, the first waiting while the review shown is not the draft's latest, unless it is
 * chosen, so that it is never chosen for a reading not shown yet; once they are left out, what
 * the calendar check lists. A round asks it under its rows instead (`RoundDecisions`). */
export function BarsChoice({
  files,
  records,
  current,
  draft,
  change,
}: BarsChoiceProps) {
  const others = draft.breaksLeftOut.filter((file) => !files.includes(file))
  const leftOut = allCorrected(files, draft.breaksLeftOut)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-foreground-secondary">{BARS_MESSAGE}</p>
      <Options
        label="Bars in a break"
        options={[
          {
            value: "leave-out",
            label: "Import the file without those bars",
            description: `FEAT leaves out ${counted(records, "record")}, those bars and the sessions listed above, and imports the rest of the file.`,
            disabled: !current && !leftOut,
          },
          {
            value: "refuse",
            label: "Do not import the file",
            description:
              "It stays refused for these bars, and nothing is written.",
          },
        ]}
        value={leftOut ? "leave-out" : "refuse"}
        onChange={(chosen) =>
          change({
            kind: "bars in breaks",
            files: chosen === "leave-out" ? [...others, ...files] : others,
          })
        }
        testId="bars-choice"
      />
      {leftOut && (
        <p className="text-xs text-muted-foreground">
          The calendar check may list the sessions left out as having no prints.
        </p>
      )}
    </div>
  )
}
