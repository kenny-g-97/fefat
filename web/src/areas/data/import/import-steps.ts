import type { ImportAsked, ImportProfile, ListedProfile } from "@/api/imports"
import type { components } from "@/api/schema"
import { counted } from "@/ui/figures"
import type { StepState } from "@/ui/stepper"
import type { Card, Draft, Missing, ProfileDraft, Source } from "./import-draft"
import type { PreviewState } from "./import-preview"
import { type Asks, listedProfile, offsetRefusal } from "./import-request"
import { OUTCOME_NAMES, VERDICTS } from "./import-outcomes"
import {
  filesToDecide,
  type NotImporting,
  type ReviewedFile,
} from "./import-reviews"

type OffsetSeen = components["schemas"]["OffsetSeen"]

/** The import wizard's steps in their order, a card each and the review last (web/DESIGN.md,
 * Patterns, Import wizard; D-105). */
export const STEPS = [
  "file",
  "layout",
  "instrument",
  "review",
] as const satisfies readonly (Card | "review")[]

export type Step = (typeof STEPS)[number]

/** The steps before the review, each a card that gives the review what it reads. */
const CARDS: readonly Card[] = ["file", "layout", "instrument"]

/** Each step's name, in the list of steps and in the name of the way back to it. */
export const STEP_NAMES: Readonly<Record<Step, string>> = {
  file: "File",
  layout: "Layout",
  instrument: "Instrument",
  review: "Review",
}

/** Where the review stands, which its step and Import's reason say: the import wrote; Import
 * has a request to send, of a round's files or of one file or batch; or what it waits for:
 * the steps before it, a read, the first or a change's, a decision on some files of a round,
 * a file or batch whose verdict does not import, or a round with no file to send. */
export type ReviewStanding =
  | Readonly<{ kind: "imported" }>
  | Readonly<{ kind: "ready"; files: number | null }>
  | Readonly<{ kind: "waiting" }>
  | Readonly<{ kind: "reading"; again: boolean }>
  | Readonly<{ kind: "to decide"; files: number }>
  | Readonly<{ kind: "not importing"; outcome: NotImporting }>
  | Readonly<{ kind: "nothing to send" }>

/** What the wizard knows of the review: what the draft asks, the request Import would send,
 * whether its import wrote, a file's or a batch's review, and a round's files with those the
 * trader skipped. */
export type ReviewFacts = Readonly<{
  asks: Asks
  request: ImportAsked | null
  imported: boolean
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

function roundStanding(
  files: readonly ReviewedFile[],
  skipped: readonly string[]
): ReviewStanding {
  const reading = files.filter(({ state }) => state.kind === "reading")
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

/** What the wizard knows when it marks its steps: the draft and what it asks, the listed
 * profiles it names, the offsets of the review the layout is read against, and where the
 * review stands. */
export type StepFacts = Readonly<{
  draft: Draft
  asks: Asks
  profiles: readonly ListedProfile[]
  offsets: readonly OffsetSeen[]
  review: ReviewStanding
}>

const NOT_NEEDED: StepState = {
  kind: "not needed",
  line: "Not needed for a batch",
}

/** Each step's state (D-105): File complete once files are chosen; Layout once a profile is
 * chosen, misses nothing, and the review finds no offset that points at it; Instrument once a
 * profile is chosen and a new instrument misses nothing; Review where Import has something to
 * send, or the import wrote. A batch needs no Layout and no Instrument. */
export function stepStates(
  facts: StepFacts
): Readonly<Record<Step, StepState>> {
  const batch = facts.draft.reading === "batch"
  const before: Readonly<Record<Card, StepState>> = {
    file: fileState(facts),
    layout: batch ? NOT_NEEDED : layoutState(facts),
    instrument: batch ? NOT_NEEDED : instrumentState(facts),
  }
  const waitingFor = CARDS.filter((card) => before[card].kind === "incomplete")
  return {
    ...before,
    review: reviewState(facts.review, waitingFor, subjectOf(facts.draft)),
  }
}

function fileState({ draft, asks }: StepFacts): StepState {
  const missing = missingOf(asks, "file")
  return missing.length > 0
    ? needing(missing)
    : { kind: "complete", line: chosenLine(draft.source) }
}

function layoutState({ draft, asks, offsets }: StepFacts): StepState {
  const missing = missingOf(asks, "layout")
  if (missing.length > 0) {
    return needing(missing)
  }
  const check = offsetCheck(offsets)
  if (check !== null) {
    return { kind: "incomplete", line: check, alert: true }
  }
  return { kind: "complete", line: profileLine(draft.profile) }
}

function instrumentState({ draft, asks, profiles }: StepFacts): StepState {
  if (draft.profile.kind === "none") {
    return waiting("Waits for Layout")
  }
  const missing = missingOf(asks, "instrument")
  return missing.length > 0
    ? needing(missing)
    : { kind: "complete", line: instrumentLine(draft, profiles) }
}

function reviewState(
  standing: ReviewStanding,
  waitingFor: readonly Card[],
  subject: Subject
): StepState {
  switch (standing.kind) {
    case "imported":
      return { kind: "complete", line: "Imported" }
    case "ready":
      return {
        kind: "complete",
        line:
          standing.files === null
            ? "Ready to import"
            : `${counted(standing.files, "file")} to import`,
      }
    case "waiting":
      return waiting(waitsForLine(waitingFor))
    case "reading":
      return waiting(`Reading the ${subject}`)
    case "to decide":
      return waiting(
        `${counted(standing.files, "file")} ${standing.files === 1 ? "waits" : "wait"} for your decision`
      )
    case "not importing":
      return waiting(OUTCOME_NAMES[standing.outcome])
    case "nothing to send":
      return waiting("No file to import")
  }
}

/** Why Import is disabled, beside it on the last step (D-105), or none where it may send:
 * the steps still to complete first, then that a read is in progress, the files that wait for a
 * decision, a file's or a batch's verdict, and a round with no file to send. */
export function importWaits(
  states: Readonly<Record<Step, StepState>>,
  standing: ReviewStanding,
  draft: Draft
): string | null {
  if (standing.kind === "imported" || standing.kind === "ready") {
    return null
  }
  const incomplete = CARDS.filter((card) => states[card].kind === "incomplete")
  if (incomplete.length > 0) {
    return `Complete ${namesOf(incomplete)} first`
  }
  const subject = subjectOf(draft)
  switch (standing.kind) {
    case "waiting":
      throw new Error(
        "Expected a step to complete while the review waits for one, got none."
      )
    case "reading":
      return standing.again
        ? "Reading your latest change"
        : `Reading the ${subject} against your data`
    case "to decide":
      return `Decide what to do with ${counted(standing.files, "file")} first`
    case "not importing":
      return standing.outcome === "unread"
        ? `The ${subject} could not be read`
        : VERDICTS[standing.outcome]
    case "nothing to send":
      return "No file to import"
  }
}

/** The steps `draft` needs, in their order: a batch needs no Layout and no Instrument. */
function neededSteps(draft: Draft): readonly Step[] {
  return draft.reading === "batch" ? ["file", "review"] : STEPS
}

/** The step shown for the address's `step`: File where it names none, or one `draft` does
 * not need, such as Layout once the draft reads a batch. */
export function shownStep(step: Step | undefined, draft: Draft): Step {
  return step !== undefined && neededSteps(draft).includes(step) ? step : "file"
}

/** The step Continue opens after `step`, past those `draft` does not need; none after the
 * last. */
export function stepAfter(step: Step, draft: Draft): Step | null {
  const needed = neededSteps(draft)
  return needed[placeOf(needed, step) + 1] ?? null
}

/** The step Back opens before `step`, past those `draft` does not need; none before the
 * first. */
export function stepBefore(step: Step, draft: Draft): Step | null {
  const needed = neededSteps(draft)
  return needed[placeOf(needed, step) - 1] ?? null
}

function placeOf(needed: readonly Step[], step: Step): number {
  const place = needed.indexOf(step)
  if (place === -1) {
    throw new Error(`Expected a step the draft needs, got ${step}.`)
  }
  return place
}

/** What the review reads, as a step's line and Import's reason name it. */
type Subject = "batch" | "files" | "file"

function subjectOf(draft: Draft): Subject {
  if (draft.reading === "batch") {
    return "batch"
  }
  return several(draft) ? "files" : "file"
}

function several(draft: Draft): boolean {
  return draft.source.kind === "uploads" && draft.source.uploads.length > 1
}

function missingOf(asks: Asks, card: Card): readonly Missing[] {
  return asks.missing.filter((missing) => missing.card === card)
}

/** A step that misses something: the one thing, or how many. */
function needing(missing: readonly Missing[]): StepState {
  const [only] = missing
  return waiting(
    missing.length === 1 && only !== undefined
      ? only.text
      : `${counted(missing.length, "thing")} to give`
  )
}

function waiting(line: string): StepState {
  return { kind: "incomplete", line, alert: false }
}

function waitsForLine(waitingFor: readonly Card[]): string {
  const [only] = waitingFor
  if (only === undefined) {
    throw new Error("Expected a step before the review to complete, got none.")
  }
  return waitingFor.length === 1
    ? `Waits for ${STEP_NAMES[only]}`
    : `Waits for ${counted(waitingFor.length, "step")}`
}

/** What to check where an offset of the review points at the layout's time zone or bar
 * stamping; none where none does. */
function offsetCheck(offsets: readonly OffsetSeen[]): string | null {
  if (offsetRefusal(offsets, "time zone") !== null) {
    return "Check the time zone"
  }
  if (offsetRefusal(offsets, "bar stamp") !== null) {
    return "Check the bar's timestamp"
  }
  return null
}

/** The files chosen in a few words: one file's name, how many, or the last part of a path,
 * so that no folder of the PC shows in the list (D-80). */
function chosenLine(source: Source): string {
  switch (source.kind) {
    case "none":
      throw new Error("Expected files chosen, got none.")
    case "uploads":
      return source.uploads.length === 1
        ? source.uploads[0].name
        : counted(source.uploads.length, "file")
    case "path":
      return lastPart(source.path)
  }
}

function lastPart(path: string): string {
  const last = path
    .trim()
    .split(/[\\/]/)
    .filter((part) => part !== "")
    .at(-1)
  return last === undefined ? path.trim() : last
}

function profileLine(profile: ProfileDraft): string {
  switch (profile.kind) {
    case "none":
      throw new Error("Expected a profile chosen, got none.")
    case "listed":
      return profile.name
    case "new":
      return `${profile.fields.name.trim()}, new`
  }
}

/** The instrument the records are of: a new one's root, the contract typed, the instrument the
 * profile carries, or the file's name, each file's of a round. */
function instrumentLine(
  draft: Draft,
  profiles: readonly ListedProfile[]
): string {
  if (draft.instrument.kind === "new") {
    return `${draft.instrument.fields.root.trim()}, new`
  }
  const contract = draft.contract.trim()
  if (contract !== "" && !several(draft)) {
    return contract
  }
  const carried = profileRead(draft.profile, profiles).instrument
  if (typeof carried === "string") {
    return carried
  }
  if (carried !== null && carried !== undefined) {
    return carried.root
  }
  return several(draft) ? "From each file's name" : "From the file's name"
}

/** The listed profile the draft reads with: its own, or the one a new profile is made from. */
function profileRead(
  profile: ProfileDraft,
  profiles: readonly ListedProfile[]
): ImportProfile {
  switch (profile.kind) {
    case "none":
      throw new Error("Expected a profile chosen, got none.")
    case "listed":
      return listedProfile(profiles, profile.name)
    case "new":
      return listedProfile(profiles, profile.base)
  }
}

/** Steps' names as a list in a sentence: "Layout", "Layout and Instrument", "File, Layout, and
 * Instrument". */
function namesOf(steps: readonly Step[]): string {
  const names = steps.map((step) => STEP_NAMES[step])
  return names.length > 2
    ? `${names.slice(0, -1).join(", ")}, and ${names.slice(-1).join("")}`
    : names.join(" and ")
}
