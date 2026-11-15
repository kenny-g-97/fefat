import type { Dispatch } from "react"
import { ApiProblem } from "@/api/problems"
import { Panel } from "@/ui/panel"
import type { Card, Draft, DraftChange } from "./import-draft"
import type { LatestPreview } from "./import-preview"
import type { Asks } from "./import-request"
import { BatchReview, FileReview } from "./FileReview"
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
  zone: string | null
}>

/** The wizard's last card (web/DESIGN.md, Patterns, Review): what is still missing, by card;
 * else what the import would do, read against the store as each change is made, the last
 * answer kept and marked while a newer one is read; then Import, and its job. */
export function ReviewCard({
  draft,
  change,
  asks,
  review,
  zone,
}: ReviewCardProps) {
  return (
    <Panel
      title="Review"
      description="What the import would add to your data, read against what FEAT holds; nothing is written until you import"
    >
      <div
        className="flex flex-col gap-5"
        data-testid="import-review"
        aria-busy={review.reading}
      >
        {asks.missing.length > 0 ? (
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
        ) : (
          <Answer draft={draft} change={change} review={review} zone={zone} />
        )}
        <Run asks={asks} review={review} />
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
    return <Refusal error={review.error} />
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

/** A request the server refused: its words, and for a request its schema refused, such as a
 * profile with a field it does not take, each refused field. */
function Refusal({ error }: Readonly<{ error: Error }>) {
  const fields = error instanceof ApiProblem ? error.refusedFields : []
  return (
    <div role="alert" className="flex flex-col gap-1 text-negative">
      <p>{error.message}</p>
      {fields.map((field) => (
        <p key={field.location.join(".")}>
          {`${field.location.slice(-2).join(" ")}: ${field.message}`}
        </p>
      ))}
    </div>
  )
}
