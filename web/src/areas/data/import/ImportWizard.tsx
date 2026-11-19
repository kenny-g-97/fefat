import {
  type ReactNode,
  type RefObject,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from "react"
import type { ImportPreviewAnswer, ListedProfile } from "@/api/imports"
import { Stepper } from "@/ui/stepper"
import { useStrayDropsIgnored } from "@/ui/stray-drops"
import { type ChosenUploads, drafted, startingDraft } from "./import-draft"
import { useLatestPreview } from "./import-preview"
import { asksOf, zoneOf } from "./import-request"
import { useFileReviews } from "./import-reviews"
import {
  filesImporting,
  filesRequest,
  leadAnswer,
  reviewedFiles,
} from "./import-round"
import { importKey, importRequest, useImportRun } from "./import-run"
import { presetChoice, type Step, STEPS } from "./import-search"
import { reviewStanding } from "./import-standing"
import {
  importWaits,
  layoutOffsets,
  shownStep,
  STEP_NAMES,
  stepStates,
} from "./import-steps"
import { FileCard } from "./FileCard"
import { InstrumentCard } from "./InstrumentCard"
import { LayoutCard } from "./LayoutCard"
import { ReviewCard } from "./ReviewCard"
import { StepFoot } from "./StepFoot"

type ImportWizardProps = Readonly<{
  profiles: readonly ListedProfile[]
  preset: string | undefined
  step: Step | undefined
  onStep: (step: Step) => void
}>

/** The wizard (web/DESIGN.md, Patterns, Import wizard, Live draft): the trader's draft, kept in
 * a reducer, from which the file's table and the review are asked as each change is made, one
 * request of each in flight; for several files (D-102), the first file's table and each file's
 * review, two requests in all in flight. Its steps stand in a list beside the one shown, the
 * address's (D-105), and every card stays drawn, those not shown hidden, so that what each
 * holds, a copy in progress, a field typed, an open confirmation, and the import's job, outlives
 * a change of step. The file's table and the review's offsets reach the cards only while they
 * are the latest draft's, and a file dropped beside the drop target is ignored. */
export function ImportWizard({
  profiles,
  preset,
  step,
  onStep,
}: ImportWizardProps) {
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
  const uploads = draft.source.kind === "uploads" ? draft.source.uploads : []
  const reviewed = several ? reviewedFiles(uploads, reviews.states) : []
  const request = several
    ? filesRequest(asks.several, reviews.states, draft.skipped)
    : importRequest(asks, review)
  const run = useImportRun(importKey(asks, draft.skipped), request)
  const first = several
    ? leadAnswer(reviewed, draft.skipped)
    : currentAnswerOf(review)
  const offsets = layoutOffsets(first)
  const standing = reviewStanding({
    asks,
    request,
    imported: run.imported,
    importing: request !== null && !run.importable,
    review,
    files: reviewed,
    skipped: draft.skipped,
  })
  const states = stepStates({
    draft,
    asks,
    profiles,
    offsets,
    review: standing,
  })
  const shown = shownStep(step, draft)
  const card = useCardShown(shown)
  const reviewLeft = (files: ChosenUploads) => {
    change({ kind: "source", source: { kind: "uploads", uploads: files } })
    reviews.readAgain()
    review.readAgain()
  }
  return (
    <div className="flex items-start gap-6">
      <Stepper
        label="Import steps"
        steps={STEPS.map((id) => ({
          id,
          name: STEP_NAMES[id],
          state: states[id],
        }))}
        current={shown}
        onStep={onStep}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <StepCard step="file" shown={shown} card={card}>
          <FileCard draft={draft} change={change} table={table} />
        </StepCard>
        {draft.reading === "file" && (
          <>
            <StepCard step="layout" shown={shown} card={card}>
              <LayoutCard
                draft={draft}
                change={change}
                profiles={profiles}
                table={read}
                preview={table}
                offsets={offsets}
              />
            </StepCard>
            <StepCard step="instrument" shown={shown} card={card}>
              <InstrumentCard
                draft={draft}
                change={change}
                profiles={profiles}
              />
            </StepCard>
          </>
        )}
        <StepCard step="review" shown={shown} card={card}>
          <ReviewCard
            draft={draft}
            change={change}
            asks={asks}
            review={review}
            files={{ reviewed, tryAgain: reviews.tryAgain }}
            run={run}
            zone={several || review.current ? zoneOf(draft, profiles) : null}
            onReviewLeft={reviewLeft}
          />
        </StepCard>
        <StepFoot
          draft={draft}
          shown={shown}
          onStep={onStep}
          run={run}
          reason={importWaits(states, standing, draft)}
          importing={several ? filesImporting(reviewed, draft.skipped) : null}
        />
      </div>
    </div>
  )
}

type StepCardProps = Readonly<{
  step: Step
  shown: Step
  card: RefObject<HTMLDivElement | null>
  children: ReactNode
}>

/** A step's card, hidden while another step is shown, and the focus's target once shown,
 * named for its step, so that a screen reader says where the focus went. */
function StepCard({ step, shown, card, children }: StepCardProps) {
  const visible = step === shown
  return (
    <div
      hidden={!visible}
      ref={visible ? card : undefined}
      tabIndex={-1}
      role="group"
      aria-label={STEP_NAMES[step]}
      className="rounded-xl"
      data-testid={`step-card-${step}`}
    >
      {children}
    </div>
  )
}

/** The frame of the card shown, which takes the focus, the page scrolled to its top, at each
 * change of step after the first, so that Continue, Back, the list, and the browser's Back each
 * land on the card they open, as the router restores no scroll of its own. */
function useCardShown(shown: Step): RefObject<HTMLDivElement | null> {
  const card = useRef<HTMLDivElement>(null)
  const last = useRef(shown)
  useEffect(() => {
    if (last.current === shown) {
      return
    }
    last.current = shown
    window.scrollTo({ top: 0, behavior: "instant" })
    card.current?.focus({ preventScroll: true })
  }, [shown])
  return card
}

/** The review's answer while it is the latest draft's. */
function currentAnswerOf(
  review: Readonly<{ current: boolean; answer: ImportPreviewAnswer | null }>
): ImportPreviewAnswer | null {
  return review.current ? review.answer : null
}
