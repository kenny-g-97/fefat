import type { Dispatch } from "react"
import type { ImportPreviewAnswer } from "@/api/imports"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import { type AsideTone, DisclosureRow } from "../DisclosureRow"
import type { Draft, DraftChange } from "./import-draft"
import {
  type FileState,
  filesWithBarsInBreaks,
  type Outcome,
  outcomeOf,
  type ReviewedFile,
  shownState,
  tallyOf,
} from "./import-reviews"
import { LeaveOutBars } from "./BarsInBreaks"
import { FileReview } from "./FileReview"
import { TakeRecords } from "./Merge"

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

/** Each outcome in a file's row, in the tone its sign takes (web/DESIGN.md, Principles):
 * a file that cannot import in the negative, one that differs in body text, the others quiet. */
const ROW_OUTCOMES: Readonly<
  Record<Outcome, Readonly<{ text: string; tone: AsideTone }>>
> = {
  imports: { text: "Imports", tone: "quiet" },
  imports_without_bars: { text: "Without bars in a break", tone: "body" },
  refused: { text: "Refused", tone: "negative" },
  bars_in_breaks: { text: "Bars in a break", tone: "body" },
  differing: { text: "Differs", tone: "body" },
  imported_before: { text: "Imported before", tone: "quiet" },
  nothing: { text: "Nothing to import", tone: "quiet" },
  unread: { text: "Not read", tone: "negative" },
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
 * other outcome, and Try again, which reads the failed files again; a row per file, which
 * opens to its own review; and, where records differ in any, what to do with them, for every
 * file at once, with no count of the stored records that give way, since two files of one
 * contract dispute the same ones: each file's own box counts its own, and the sum is the
 * import's to give. */
export function FilesReview({
  files,
  tryAgain,
  draft,
  change,
  zone,
}: FilesReviewProps) {
  const states = files.map((file) => file.state)
  const shown = states.map(shownState)
  const tally = tallyOf(shown)
  const withBreaks = filesWithBarsInBreaks(files)
  const merges = shown.flatMap((state) =>
    state.kind === "answered" &&
    state.answer.kind === "file" &&
    state.answer.merge !== null
      ? [state.answer.merge]
      : []
  )
  return (
    <div className="flex flex-col gap-4">
      {tally.read < files.length ? (
        <p
          className="text-xs text-muted-foreground"
          data-testid="review-reading"
        >
          {`Read ${tally.read} of ${files.length} files`}
        </p>
      ) : (
        <Headline outcomes={tally.outcomes} files={files.length} />
      )}
      {tally.read === files.length &&
        states.some((state) => state.kind === "reading") && (
          <p className="text-xs text-muted-foreground">
            Reading your latest change
          </p>
        )}
      {states.some((state) => state.kind === "failed") && (
        <Button variant="ghost" className="self-start" onClick={tryAgain}>
          Try again
        </Button>
      )}
      <div data-testid="review-files" className="border-b">
        {files.map(({ upload, state }) => (
          <FileRow
            key={upload.id}
            name={upload.name}
            state={state}
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
    </div>
  )
}

function Headline({
  outcomes,
  files,
}: Readonly<{ outcomes: Readonly<Record<Outcome, number>>; files: number }>) {
  const others = OTHER_OUTCOMES.flatMap(({ outcome, one, several }) => {
    const count = outcomes[outcome]
    return count === 0
      ? []
      : [`${counted(count, "file")} ${count === 1 ? one : several}`]
  })
  return (
    <div className="flex flex-col gap-1">
      <p
        data-testid="review-files-verdict"
        className="text-base font-semibold text-foreground"
      >
        {`${outcomes.imports} of ${counted(files, "file")} import as they are`}
      </p>
      {others.map((line) => (
        <p key={line} className="text-foreground-secondary">
          {line}
        </p>
      ))}
    </div>
  )
}

type FileRowProps = Readonly<{
  name: string
  state: FileState
  draft: Draft
  change: Dispatch<DraftChange>
  zone: string | null
}>

/** A file's row: its name, its records or why it was not read, and its outcome in its tone,
 * opening to its own review; while it is read again after a change, its last review, marked
 * as one to read again. */
function FileRow({ name, state, draft, change, zone }: FileRowProps) {
  const shown = shownState(state)
  const outcome = outcomeOf(shown)
  const aside = asideOf(state, outcome)
  if (shown.kind === "answered" && shown.answer.kind === "file") {
    const seen = shown.answer
    return (
      <DisclosureRow
        testId="review-file"
        name={name}
        note={`${counted(seen.records, "record")}, ${seen.contracts.join(", ") || "no contract"}`}
        aside={aside.text}
        asideTone={aside.tone}
      >
        <div className="pb-4">
          <FileReview
            seen={seen}
            draft={draft}
            change={change}
            zone={zone}
            alone={false}
          />
        </div>
      </DisclosureRow>
    )
  }
  if (shown.kind === "reading") {
    return (
      <DisclosureRow testId="review-file" name={name} note="Not read yet">
        <p className="pb-3 text-xs text-muted-foreground">
          Its review shows here once it is read.
        </p>
      </DisclosureRow>
    )
  }
  return (
    <DisclosureRow
      testId="review-file"
      name={name}
      note="Not read: open for why"
      aside={aside.text}
      asideTone={aside.tone}
    >
      <p role="alert" className="pb-3 text-negative">
        {shown.kind === "failed" ? shown.error.message : reasonOf(shown.answer)}
      </p>
    </DisclosureRow>
  )
}

/** A row's outcome, or that its last review is to be read again. */
function asideOf(
  state: FileState,
  outcome: Outcome | null
): Readonly<{ text: string; tone: AsideTone }> {
  if (state.kind === "reading" || outcome === null) {
    return { text: "To read again", tone: "quiet" }
  }
  return ROW_OUTCOMES[outcome]
}

function reasonOf(answer: ImportPreviewAnswer): string {
  return answer.kind === "refused"
    ? answer.message
    : `Expected a file's review, got a ${answer.kind} one.`
}
