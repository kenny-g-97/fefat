import { useMemo, useReducer } from "react"
import type {
  FileSeen,
  ImportPreviewAnswer,
  ListedProfile,
} from "@/api/imports"
import { useStrayDropsIgnored } from "@/ui/stray-drops"
import { type ChosenUploads, drafted, startingDraft } from "./import-draft"
import { useLatestPreview } from "./import-preview"
import { asksOf, zoneOf } from "./import-request"
import { type FileState, useFileReviews } from "./import-reviews"
import { presetChoice } from "./import-search"
import { FileCard } from "./FileCard"
import { InstrumentCard } from "./InstrumentCard"
import { LayoutCard } from "./LayoutCard"
import { ReviewCard } from "./ReviewCard"

const NO_OFFSETS: FileSeen["offsets"] = []

type ImportWizardProps = Readonly<{
  profiles: readonly ListedProfile[]
  preset: string | undefined
}>

/** The wizard (web/DESIGN.md, Patterns, Import wizard, Live draft): the trader's draft, kept in
 * a reducer, from which the file's table and the review are asked as each change is made, one
 * request of each in flight; for several files (D-102), the first file's table and each file's
 * review, two requests in all in flight. A select acts at once, and typed text once its field
 * is left. The file's table and the review's offsets, the first file's, reach the cards above
 * only while they are the latest draft's, and a file dropped beside the drop target is ignored
 * rather than opened. */
export function ImportWizard({ profiles, preset }: ImportWizardProps) {
  const [draft, change] = useReducer(
    drafted,
    presetChoice(preset, profiles),
    startingDraft
  )
  useStrayDropsIgnored()
  const tableAsked = useMemo(
    () => asksOf(draft, profiles, null).table,
    [draft, profiles]
  )
  const table = useLatestPreview(tableAsked)
  const read =
    table.current && table.answer?.kind === "table" ? table.answer : null
  const asks = useMemo(
    () => asksOf(draft, profiles, read),
    [draft, profiles, read]
  )
  const review = useLatestPreview(asks.review)
  const reviews = useFileReviews(asks.several, table.reading ? 1 : 2)
  const several = asks.several.length > 0
  const first = several ? answerOf(reviews.states) : currentAnswerOf(review)
  const offsets = first?.kind === "file" ? first.offsets : NO_OFFSETS
  const reviewLeft = (files: ChosenUploads) => {
    change({ kind: "source", source: { kind: "uploads", uploads: files } })
    reviews.readAgain()
    review.readAgain()
  }
  return (
    <div className="flex flex-col gap-6">
      <FileCard draft={draft} change={change} table={table} />
      {draft.reading === "file" && (
        <>
          <LayoutCard
            draft={draft}
            change={change}
            profiles={profiles}
            table={read}
            offsets={offsets}
          />
          <InstrumentCard draft={draft} change={change} profiles={profiles} />
        </>
      )}
      <ReviewCard
        draft={draft}
        change={change}
        asks={asks}
        review={review}
        reviews={reviews}
        zone={several || review.current ? zoneOf(draft, profiles) : null}
        onReviewLeft={reviewLeft}
      />
    </div>
  )
}

/** The first file's answer, once read. */
function answerOf(states: readonly FileState[]): ImportPreviewAnswer | null {
  const [first] = states
  return first !== undefined && first.kind === "answered" ? first.answer : null
}

/** The review's answer while it is the latest draft's. */
function currentAnswerOf(
  review: Readonly<{ current: boolean; answer: ImportPreviewAnswer | null }>
): ImportPreviewAnswer | null {
  return review.current ? review.answer : null
}
