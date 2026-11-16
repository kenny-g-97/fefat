import type { Dispatch } from "react"
import { ApiProblem } from "@/api/problems"
import { Button } from "@/ui/button"
import { Panel } from "@/ui/panel"
import type { Card, ChosenUploads, Draft, DraftChange } from "./import-draft"
import type { LatestPreview } from "./import-preview"
import type { Asks } from "./import-request"
import { type FileReviews, filesRequest, reviewedFiles } from "./import-reviews"
import { importKey, importRequest, useImportRun } from "./import-run"
import { BatchReview, FileReview } from "./FileReview"
import { FilesReview } from "./FilesReview"
import { Run } from "./Run"

const CARD_NAMES: Readonly<Record<Card, string>> = {
  file: "File",
  layout: "Layout",
  instrument: "Instrument",
}

type ReviewCardProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
  asks: Asks
  review: LatestPreview
  reviews: FileReviews
  zone: string | null
  onReviewLeft: (files: ChosenUploads) => void
}>

/** The wizard's last card (web/DESIGN.md, Patterns, Review): what is still missing, by card;
 * else what the import would do, read against the store as each change is made, the last
 * answer kept and marked while a newer one is read, or for several files each file's review
 * (`FilesReview`), until the import of what it shows wrote; then Import, and its job. */
export function ReviewCard({
  draft,
  change,
  asks,
  review,
  reviews,
  zone,
  onReviewLeft,
}: ReviewCardProps) {
  const several = asks.several.length > 0
  const run = useImportRun(
    importKey(asks),
    several
      ? filesRequest(asks.several, reviews.states)
      : importRequest(asks, review)
  )
  const uploads = draft.source.kind === "uploads" ? draft.source.uploads : []
  const reading = several
    ? reviews.states.some((state) => state.kind === "reading")
    : review.reading
  return (
    <Panel
      title="Review"
      description="What the import would add to your data, read against what FEAT holds; nothing is written until you import"
    >
      <div
        className="flex flex-col gap-5"
        data-testid="import-review"
        aria-busy={reading}
      >
        {asks.missing.length > 0 && (
          <ul
            className="flex flex-col gap-1 text-foreground-secondary"
            data-testid="import-missing"
          >
            {asks.missing.map((missing) => (
              <li key={`${missing.card} ${missing.text}`}>
                <span className="font-medium text-foreground">
                  {CARD_NAMES[missing.card]}
                </span>
                : {missing.text}
              </li>
            ))}
          </ul>
        )}
        {asks.missing.length === 0 && !run.imported && several && (
          <FilesReview
            files={reviewedFiles(uploads, reviews.states)}
            readAgain={reviews.readAgain}
            draft={draft}
            change={change}
            zone={zone}
          />
        )}
        {asks.missing.length === 0 && !run.imported && !several && (
          <Answer draft={draft} change={change} review={review} zone={zone} />
        )}
        <Run run={run} reading={reading} files={{ uploads, onReviewLeft }} />
      </div>
    </Panel>
  )
}

type AnswerProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
  review: LatestPreview
  zone: string | null
}>

function Answer({ draft, change, review, zone }: AnswerProps) {
  if (review.error !== null) {
    return <Refusal error={review.error} onRetry={review.readAgain} />
  }
  const answer = review.answer
  return (
    <div className="flex flex-col gap-5">
      {review.reading && (
        <p
          className="text-xs text-muted-foreground"
          data-testid="review-reading"
        >
          {answer === null
            ? "Reading the file against your data"
            : "Reading your latest change"}
        </p>
      )}
      {answer?.kind === "refused" && (
        <p role="alert" className="text-negative">
          {answer.message}
        </p>
      )}
      {answer?.kind === "file" && (
        <FileReview seen={answer} draft={draft} change={change} zone={zone} />
      )}
      {answer?.kind === "databento" && (
        <BatchReview seen={answer} draft={draft} change={change} />
      )}
    </div>
  )
}

/** A request the server refused or could not answer (web/DESIGN.md, Patterns, Section
 * failure): its words, and for a request its schema refused, such as a profile with a field it
 * does not take, each refused field; then Try again, which reads the same draft anew. */
function Refusal({
  error,
  onRetry,
}: Readonly<{ error: Error; onRetry: () => void }>) {
  const fields = error instanceof ApiProblem ? error.refusedFields : []
  return (
    <div className="flex flex-col items-start gap-3">
      <div role="alert" className="flex flex-col gap-1 text-negative">
        <p>{error.message}</p>
        {fields.map((field) => (
          <p key={field.location.join(".")}>
            {`${field.location.slice(-2).join(" ")}: ${field.message}`}
          </p>
        ))}
      </div>
      <Button variant="ghost" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}
