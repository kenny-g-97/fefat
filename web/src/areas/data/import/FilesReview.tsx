import type { Dispatch } from "react"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import { type AsideTone, DisclosureRow } from "../DisclosureRow"
import type { Draft, DraftChange } from "./import-draft"
import {
  type FileState,
  type Outcome,
  outcomeOf,
  shownState,
  tallyOf,
} from "./import-reviews"
import {
  filesToDecide,
  filesWithBarsInBreaks,
  notSkipped,
  type ReviewedFile,
} from "./import-round"
import { LeaveOutBars } from "./BarsInBreaks"
import { OUTCOME_NAMES, OUTCOME_SIGNS, whyNot } from "./import-outcomes"
import { FileReview } from "./FileReview"
import { TakeRecords } from "./Merge"
import { SkipFile, SkipFiles } from "./SkipFiles"

/** What the files of each outcome but `imports` would do, as the headline's lines say it, for
 * one file and for several. */
const OTHER_OUTCOMES: readonly Readonly<{
  outcome: Exclude<Outcome, "imports">
  one: string
  several: string
}>[] = [
  {
    outcome: "imports_without_bars",
    one: "imports without its bars in a break",
    several: "import without their bars in a break",
  },
  { outcome: "refused", one: "would be refused", several: "would be refused" },
  {
    outcome: "bars_in_breaks",
    one: "would be refused for its bars in a break",
    several: "would be refused for their bars in a break",
  },
  {
    outcome: "differing",
    one: "holds records that differ from the ones FEAT holds",
    several: "hold records that differ from the ones FEAT holds",
  },
  {
    outcome: "imported_before",
    one: "is imported already",
    several: "are imported already",
  },
  {
    outcome: "nothing",
    one: "holds nothing to import",
    several: "hold nothing to import",
  },
  { outcome: "unread", one: "could not be read", several: "could not be read" },
]

/** The tone each sign of an outcome takes in a file's row (D-105): a file that imports in the
 * positive, one that something stops in the negative, and one imported before or empty quiet. */
const ROW_TONES: Readonly<Record<(typeof OUTCOME_SIGNS)[Outcome], AsideTone>> =
  {
    positive: "positive",
    negative: "negative",
    none: "quiet",
  }

type FilesReviewProps = Readonly<{
  files: readonly ReviewedFile[]
  tryAgain: () => void
  draft: Draft
  change: Dispatch<DraftChange>
  zone: string | null
}>

/** What the import of several files would do (web/DESIGN.md, Patterns, Review, several
 * files; D-102): how many are read, then how many import as they are, with a line for each
 * other outcome and for the files skipped, and Try again, which reads the failed files again; a
 * row per file, which opens to its own review; where records differ in any, what to do with
 * them, for every file at once, with no count of the stored records that give way, since two
 * files of one contract dispute the same ones: each file's own box counts its own, and the sum
 * is the import's to give; and a decision on each file that does not import (D-105), a skip for
 * those left at once, the corrections and the skips leaving the skipped files out. */
export function FilesReview({
  files,
  tryAgain,
  draft,
  change,
  zone,
}: FilesReviewProps) {
  const skipped = draft.skipped
  const kept = notSkipped(files, skipped)
  const shown = kept.map(({ state }) => shownState(state))
  const tally = tallyOf(shown)
  const read = files.filter(
    ({ state }) => shownState(state).kind !== "reading"
  ).length
  const withBreaks = filesWithBarsInBreaks(files, skipped)
  const toDecide = filesToDecide(files, skipped).map(({ upload }) => upload.id)
  const merges = shown.flatMap((state) =>
    state.kind === "answered" &&
    state.answer.kind === "file" &&
    state.answer.merge !== null
      ? [state.answer.merge]
      : []
  )
  return (
    <div className="flex flex-col gap-4">
      {read < files.length ? (
        <p
          className="text-xs text-muted-foreground"
          data-testid="review-reading"
        >
          {`Read ${read} of ${files.length} files`}
        </p>
      ) : (
        <Headline
          outcomes={tally.outcomes}
          files={files.length}
          skipped={files.length - kept.length}
        />
      )}
      {read === files.length &&
        files.some(({ state }) => state.kind === "reading") && (
          <p className="text-xs text-muted-foreground">
            Reading your latest change
          </p>
        )}
      {files.some(({ state }) => state.kind === "failed") && (
        <Button variant="ghost" className="self-start" onClick={tryAgain}>
          Try again
        </Button>
      )}
      <div data-testid="review-files" className="border-b">
        {files.map((file) => (
          <FileRow
            key={file.upload.id}
            file={file}
            skipped={skipped.includes(file.upload.id)}
            decides={
              skipped.includes(file.upload.id) ||
              toDecide.includes(file.upload.id)
            }
            draft={draft}
            change={change}
            zone={zone}
          />
        ))}
      </div>
      {withBreaks.length > 0 && (
        <LeaveOutBars
          files={withBreaks}
          records={null}
          draft={draft}
          change={change}
        />
      )}
      {merges.some((merge) => merge.records_differing > 0) && (
        <TakeRecords disputed={null} draft={draft} change={change} />
      )}
      {read === files.length && (
        <SkipFiles toDecide={toDecide} draft={draft} change={change} />
      )}
    </div>
  )
}

type HeadlineProps = Readonly<{
  outcomes: Readonly<Record<Outcome, number>>
  files: number
  skipped: number
}>

function Headline({ outcomes, files, skipped }: HeadlineProps) {
  const others = OTHER_OUTCOMES.flatMap(({ outcome, one, several }) => {
    const count = outcomes[outcome]
    return count === 0
      ? []
      : [`${counted(count, "file")} ${count === 1 ? one : several}`]
  })
  const skips =
    skipped === 0
      ? []
      : [
          `${counted(skipped, "file")} ${skipped === 1 ? "is" : "are"} skipped, as you chose`,
        ]
  return (
    <div className="flex flex-col gap-1">
      <p
        data-testid="review-files-verdict"
        className="text-base font-semibold text-foreground"
      >
        {`${outcomes.imports} of ${counted(files, "file")} import as they are`}
      </p>
      {[...others, ...skips].map((line) => (
        <p key={line} className="text-foreground-secondary">
          {line}
        </p>
      ))}
    </div>
  )
}

type FileRowProps = Readonly<{
  file: ReviewedFile
  skipped: boolean
  decides: boolean
  draft: Draft
  change: Dispatch<DraftChange>
  zone: string | null
}>

/** A file's row: its name, its records, and its outcome in its sign's colour, with what stops
 * it under its name, where something does (D-105), opening to its own review, or for a file not
 * read to why, which ends on Skip this file where the file waits for a decision; a skipped row
 * reads Skipped, quiet; and while it is read again after a change, its last review, marked as
 * one to read again. */
function FileRow({
  file,
  skipped,
  decides,
  draft,
  change,
  zone,
}: FileRowProps) {
  const { upload, state } = file
  const shown = shownState(state)
  const aside = skipped ? SKIPPED : asideOf(state, outcomeOf(shown))
  const reason = skipped ? null : whyNot(state, zone)
  const skip = (
    <SkipFile
      file={upload.id}
      offered={decides}
      draft={draft}
      change={change}
    />
  )
  if (shown.kind === "answered" && shown.answer.kind === "file") {
    const seen = shown.answer
    return (
      <DisclosureRow
        testId="review-file"
        name={upload.name}
        note={`${counted(seen.records, "record")}, ${seen.contracts.join(", ") || "no contract"}`}
        aside={aside.text}
        asideTone={aside.tone}
        reason={reason}
      >
        <div className="flex flex-col gap-4 pb-4">
          <FileReview
            seen={seen}
            draft={draft}
            change={change}
            zone={zone}
            alone={false}
          />
          {skip}
        </div>
      </DisclosureRow>
    )
  }
  if (shown.kind === "reading") {
    return (
      <DisclosureRow
        testId="review-file"
        name={upload.name}
        note="Not read yet"
      >
        <p className="pb-3 text-xs text-muted-foreground">
          Its review shows here once it is read.
        </p>
      </DisclosureRow>
    )
  }
  const why = whyNot(shown, zone)
  return (
    <DisclosureRow
      testId="review-file"
      name={upload.name}
      aside={aside.text}
      asideTone={aside.tone}
      reason={reason}
    >
      <div className="flex flex-col items-start gap-3 pb-3">
        {why !== null && (
          <p className="text-negative" data-testid="review-file-why">
            {why}
          </p>
        )}
        {skip}
      </div>
    </DisclosureRow>
  )
}

const SKIPPED: Readonly<{ text: string; tone: AsideTone }> = {
  text: "Skipped",
  tone: "quiet",
}

/** A row's outcome, or that its last review is to be read again. */
function asideOf(
  state: FileState,
  outcome: Outcome | null
): Readonly<{ text: string; tone: AsideTone }> {
  if (state.kind === "reading" || outcome === null) {
    return { text: "To read again", tone: "quiet" }
  }
  return {
    text: OUTCOME_NAMES[outcome],
    tone: ROW_TONES[OUTCOME_SIGNS[outcome]],
  }
}
