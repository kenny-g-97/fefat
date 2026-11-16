import type { Dispatch } from "react"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import { DisclosureRow } from "../DisclosureRow"
import type { Draft, DraftChange } from "./import-draft"
import {
  type FileState,
  type Outcome,
  outcomeOf,
  type ReviewedFile,
  tallyOf,
} from "./import-reviews"
import { FileReview } from "./FileReview"
import { TakeRecords } from "./Merge"

/** What the files of each outcome but `imports` would do, as the headline's lines say it, for
 * one file and for several. */
const OTHER_OUTCOMES: readonly Readonly<{
  outcome: Exclude<Outcome, "imports">
  one: string
  several: string
}>[] = [
  { outcome: "refused", one: "would be refused", several: "would be refused" },
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

/** Each outcome in a file's row. */
const ROW_OUTCOMES: Readonly<Record<Outcome, string>> = {
  imports: "Imports",
  refused: "Refused",
  differing: "Differs",
  imported_before: "Imported before",
  nothing: "Nothing to import",
  unread: "Not read",
}

type FilesReviewProps = Readonly<{
  files: readonly ReviewedFile[]
  readAgain: () => void
  draft: Draft
  change: Dispatch<DraftChange>
  zone: string | null
}>

/** What the import of several files would do (web/DESIGN.md, Patterns, Review, several
 * files; D-102): how many are read, then how many import as they are, with a line for each
 * other outcome; a row per file, which opens to its own review; and, where records differ in
 * any, what to do with them, for every file at once, the stored records that give way counted
 * over all of them. Each file's records are its own: their sum is the import's to give. */
export function FilesReview({
  files,
  readAgain,
  draft,
  change,
  zone,
}: FilesReviewProps) {
  const states = files.map((file) => file.state)
  const tally = tallyOf(states)
  const merges = states.flatMap((state) =>
    state.kind === "answered" &&
    state.answer.kind === "file" &&
    state.answer.merge !== null
      ? [state.answer.merge]
      : []
  )
  const disputed = merges.reduce(
    (total, merge) => total + merge.stored_records_disputed,
    0
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
      {states.some((state) => state.kind === "failed") && (
        <Button variant="ghost" className="self-start" onClick={readAgain}>
          Try again
        </Button>
      )}
      <div data-testid="review-files">
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
      {merges.some((merge) => merge.records_differing > 0) && (
        <TakeRecords disputed={disputed} draft={draft} change={change} />
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

/** A file's row: its name, its records or why it was not read, and its outcome, opening to its
 * own review. */
function FileRow({ name, state, draft, change, zone }: FileRowProps) {
  const outcome = outcomeOf(state)
  const aside = outcome === null ? "Reading" : ROW_OUTCOMES[outcome]
  if (state.kind === "answered" && state.answer.kind === "file") {
    const seen = state.answer
    return (
      <DisclosureRow
        testId="review-file"
        name={name}
        note={`${counted(seen.records, "record")}, ${seen.contracts.join(", ") || "no contract"}`}
        aside={aside}
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
  return (
    <DisclosureRow
      testId="review-file"
      name={name}
      note={noteOf(state)}
      aside={aside}
    >
      <p role="alert" className="pb-3 text-negative">
        {reasonOf(state)}
      </p>
    </DisclosureRow>
  )
}

function noteOf(state: FileState): string {
  return state.kind === "reading" ? "Being read" : "Not read: open for why"
}

function reasonOf(state: FileState): string {
  switch (state.kind) {
    case "reading":
      return "Its review is being read."
    case "failed":
      return state.error.message
    case "answered":
      return state.answer.kind === "refused"
        ? state.answer.message
        : `Expected a file's review, got a ${state.answer.kind} one.`
  }
}
