import type { ImportAsked } from "@/api/imports"
import type { PreviewState } from "./import-preview"
import type { Asks } from "./import-request"
import type { NotImporting } from "./import-reviews"
import { filesToDecide, notSkipped, type ReviewedFile } from "./import-round"

/** Where the review stands, which its step and Import's reason say: the import wrote, or was
 * sent and runs; Import has a request to send, of a round's files or of one file or batch; or
 * what it waits for: the steps before it, a read, the first or a change's, a decision on some
 * files of a round, a file or batch whose verdict does not import, or a round with no file to
 * send (D-105). */
export type ReviewStanding =
  | Readonly<{ kind: "imported" }>
  | Readonly<{ kind: "importing" }>
  | Readonly<{ kind: "ready"; files: number | null }>
  | Readonly<{ kind: "waiting" }>
  | Readonly<{ kind: "reading"; again: boolean }>
  | Readonly<{ kind: "to decide"; files: number }>
  | Readonly<{ kind: "not importing"; outcome: NotImporting }>
  | Readonly<{ kind: "nothing to send" }>

/** What the wizard knows of the review: what the draft asks, the request Import would send,
 * whether its import wrote or was sent and has not ended, a file's or a batch's review, and a
 * round's files with those the trader skipped. */
export type ReviewFacts = Readonly<{
  asks: Asks
  request: ImportAsked | null
  imported: boolean
  importing: boolean
  review: Pick<PreviewState, "answer" | "current" | "reading" | "error">
  files: readonly ReviewedFile[]
  skipped: readonly string[]
}>

/** Where the review stands (`ReviewStanding`): ready exactly where Import has a request to
 * send, its one gate (D-105). */
export function reviewStanding(facts: ReviewFacts): ReviewStanding {
  if (facts.imported) {
    return { kind: "imported" }
  }
  if (facts.importing) {
    return { kind: "importing" }
  }
  const request = facts.request
  if (request !== null) {
    const files = request.kind === "files" ? request.sources.length : null
    return { kind: "ready", files }
  }
  if (facts.asks.missing.length > 0) {
    return { kind: "waiting" }
  }
  return facts.asks.several.length > 0
    ? roundStanding(facts.files, facts.skipped)
    : oneStanding(facts.review)
}

/** A round's standing, by its files not skipped alone, since a skipped file's read holds
 * nothing back. */
function roundStanding(
  files: readonly ReviewedFile[],
  skipped: readonly string[]
): ReviewStanding {
  const reading = notSkipped(files, skipped).filter(
    ({ state }) => state.kind === "reading"
  )
  if (reading.length > 0) {
    const again = reading.some(
      ({ state }) => state.kind === "reading" && state.last !== null
    )
    return { kind: "reading", again }
  }
  const toDecide = filesToDecide(files, skipped)
  if (toDecide.length > 0) {
    return { kind: "to decide", files: toDecide.length }
  }
  return { kind: "nothing to send" }
}

function oneStanding(review: ReviewFacts["review"]): ReviewStanding {
  if (review.error !== null) {
    return { kind: "not importing", outcome: "unread" }
  }
  const answer = review.current ? review.answer : null
  if (answer === null) {
    return { kind: "reading", again: review.answer !== null }
  }
  if (answer.kind === "refused" || answer.kind === "table") {
    return { kind: "not importing", outcome: "unread" }
  }
  if (answer.verdict === "imports") {
    throw new Error(
      "Expected Import's request for a review that imports, got none."
    )
  }
  return { kind: "not importing", outcome: answer.verdict }
}
