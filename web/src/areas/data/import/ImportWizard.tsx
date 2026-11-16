import { useMemo, useReducer } from "react"
import type { FileSeen, ListedProfile } from "@/api/imports"
import { useStrayDropsIgnored } from "@/ui/stray-drops"
import { drafted, startingDraft } from "./import-draft"
import { useLatestPreview } from "./import-preview"
import { asksOf, zoneOf } from "./import-request"
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
 * request of each in flight; a select acts at once, and typed text once its field is left. The
 * file's table and the review's offsets reach the cards above only while they are the latest
 * draft's, and a file dropped beside the drop target is ignored rather than opened. */
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
  const offsets =
    review.current && review.answer?.kind === "file"
      ? review.answer.offsets
      : NO_OFFSETS
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
        zone={review.current ? zoneOf(draft, profiles) : null}
      />
    </div>
  )
}
