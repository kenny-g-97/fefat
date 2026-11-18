import { type Dispatch, useRef } from "react"
import { ApiProblem } from "@/api/problems"
import { Button } from "@/ui/button"
import { Panel } from "@/ui/panel"
import type { ChosenUploads, Draft, DraftChange } from "./import-draft"
import type { LatestPreview } from "./import-preview"
import type { Asks } from "./import-request"
import type { ReviewedFile } from "./import-reviews"
import type { ImportRun } from "./import-run"
import { STEP_NAMES } from "./import-steps"
import { BatchReview, FileReview } from "./FileReview"
import { FilesReview } from "./FilesReview"
import { ImportJob } from "./Run"

type ReviewCardProps = Readonly<{
  draft: Draft
  change: Dispatch<DraftChange>
  asks: Asks
  review: LatestPreview
  files: Readonly<{ reviewed: readonly ReviewedFile[]; tryAgain: () => void }>
  run: ImportRun
  zone: string | null
  onReviewLeft: (files: ChosenUploads) => void
}>

/** The wizard's last step (web/DESIGN.md, Patterns, Review): what is still missing, by step;
 * else what the import would do, read against the store as each change is made, the last
 * answer kept and marked while a newer one is read, or for several files each file's review
 * (`FilesReview`), until the import of what it shows wrote; then the import's job, which the
 * wizard runs, Import standing under the card (D-105). */
export function ReviewCard({
  draft,
  change,
  asks,
  review,
  files,
  run,
  zone,
  onReviewLeft,
}: ReviewCardProps) {
  const several = asks.several.length > 0
  const focused = useRef<HTMLDivElement>(null)
  const reading = several
    ? files.reviewed.some(({ state }) => state.kind === "reading")
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
        ref={focused}
        tabIndex={-1}
      >
        {asks.missing.length > 0 && (
          <ul
            className="flex flex-col gap-1 text-foreground-secondary"
            data-testid="import-missing"
          >
            {asks.missing.map((missing) => (
              <li key={`${missing.card} ${missing.text}`}>
                <span className="font-medium text-foreground">
                  {STEP_NAMES[missing.card]}
                </span>
                : {missing.text}
              </li>
            ))}
          </ul>
        )}
        {asks.missing.length === 0 && !run.imported && several && (
          <FilesReview
            files={files.reviewed}
            tryAgain={files.tryAgain}
            draft={draft}
            change={change}
            zone={zone}
          />
        )}
        {asks.missing.length === 0 && !run.imported && !several && (
          <Answer draft={draft} change={change} review={review} zone={zone} />
        )}
        {run.job !== undefined && (
          <ImportJob
            job={run.job}
            sent={run.sent}
            files={{
              reviewed: files.reviewed,
              onReviewLeft: (left) => {
                onReviewLeft(left)
                focused.current?.focus()
              },
            }}
          />
        )}
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
