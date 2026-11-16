import { useEffect, useMemo, useReducer, useRef, useState } from "react"
import {
  type ImportPreviewAnswer,
  previewOf,
  type UploadedFile,
} from "@/api/imports"
import type { components } from "@/api/schema"

type Schemas = components["schemas"]
type FileImportAsked = Schemas["FileImportAsked"]
type FilesImportAsked = Schemas["FilesImportAsked"]
type ImportSource = Schemas["ImportSource"]

/** How many files one import takes in a round, as the server's `FILES_AT_MOST` (D-102). */
export const FILES_AT_MOST = 200

/** A file's review once its request came back: the server's answer, or why it failed. */
export type Settled =
  | Readonly<{ kind: "answered"; answer: ImportPreviewAnswer }>
  | Readonly<{ kind: "failed"; error: Error }>

/** A file's review in the round's list: being read, or settled. */
export type FileState = Readonly<{ kind: "reading" }> | Settled

/** Several files' reviews (web/DESIGN.md, Patterns, Live draft): the latest draft's asks, one
 * per file in the files' order, each its request's JSON after the number of times the page
 * asked to read again; the requests in flight, an older draft's among them, since each holds a
 * runner of the server's until it settles; and the latest asks' answers and failures. */
export type ReviewsQueue = Readonly<{
  asks: readonly string[]
  inFlight: readonly string[]
  settled: ReadonlyMap<string, Settled>
}>

export const EMPTY_REVIEWS: ReviewsQueue = {
  asks: [],
  inFlight: [],
  settled: new Map(),
}

export type ReviewsChange =
  | Readonly<{ kind: "listed"; asks: readonly string[] }>
  | Readonly<{ kind: "sent"; ask: string }>
  | Readonly<{ kind: "answered"; ask: string; answer: ImportPreviewAnswer }>
  | Readonly<{ kind: "failed"; ask: string; error: Error }>

/** The queue after `change`: a new list keeps the answers of the asks it still holds, and an
 * answer to an ask no longer listed only frees its place. */
export function reviewsQueued(
  queue: ReviewsQueue,
  change: ReviewsChange
): ReviewsQueue {
  switch (change.kind) {
    case "listed": {
      const kept = [...queue.settled].filter(([ask]) =>
        change.asks.includes(ask)
      )
      return { ...queue, asks: change.asks, settled: new Map(kept) }
    }
    case "sent":
      return queue.inFlight.includes(change.ask)
        ? queue
        : { ...queue, inFlight: [...queue.inFlight, change.ask] }
    case "answered":
      return settledBy(queue, change.ask, {
        kind: "answered",
        answer: change.answer,
      })
    case "failed":
      return settledBy(queue, change.ask, {
        kind: "failed",
        error: change.error,
      })
  }
}

function settledBy(
  queue: ReviewsQueue,
  ask: string,
  settled: Settled
): ReviewsQueue {
  const inFlight = queue.inFlight.filter((each) => each !== ask)
  if (!queue.asks.includes(ask)) {
    return { ...queue, inFlight }
  }
  return {
    ...queue,
    inFlight,
    settled: new Map(queue.settled).set(ask, settled),
  }
}

/** The next ask to send, the first not read yet in the files' order, while fewer than `most`
 * requests are in flight; a failed one is settled and goes again only with a new reading. */
export function nextReview(
  queue: ReviewsQueue,
  most: number
): string | undefined {
  if (queue.inFlight.length >= most) {
    return undefined
  }
  return queue.asks.find(
    (ask) => !queue.inFlight.includes(ask) && !queue.settled.has(ask)
  )
}

const READING: FileState = { kind: "reading" }

/** The review of each of `asks`, in their order: being read until it settles. */
export function fileStates(
  queue: ReviewsQueue,
  asks: readonly string[]
): readonly FileState[] {
  return asks.map((ask) => queue.settled.get(ask) ?? READING)
}

/** A file of several and its review. */
export type ReviewedFile = Readonly<{ upload: UploadedFile; state: FileState }>

/** Each of `uploads` with its review, `states` holding one for each in their order. */
export function reviewedFiles(
  uploads: readonly UploadedFile[],
  states: readonly FileState[]
): readonly ReviewedFile[] {
  requireOnePerFile(uploads.length, states)
  return uploads.map((upload, index) => ({ upload, state: states[index] }))
}

function requireOnePerFile(files: number, states: readonly FileState[]) {
  if (states.length !== files) {
    throw new Error(
      `Expected a review of each of the ${files} files, got ${states.length}.`
    )
  }
}

/** What a file's review says of its import: a verdict, or that the file could not be read,
 * refused before a verdict or failed. */
export type Outcome = Schemas["ImportVerdict"] | "unread"

/** What `state` says of its file's import; none while it is read. */
export function outcomeOf(state: FileState): Outcome | null {
  if (state.kind === "reading") {
    return null
  }
  if (state.kind === "failed" || state.answer.kind !== "file") {
    return "unread"
  }
  return state.answer.verdict
}

/** How many files were read, and how many of them each outcome holds. */
export type Tally = Readonly<{
  read: number
  outcomes: Readonly<Record<Outcome, number>>
}>

export function tallyOf(states: readonly FileState[]): Tally {
  const outcomes: Record<Outcome, number> = {
    imports: 0,
    refused: 0,
    differing: 0,
    imported_before: 0,
    nothing: 0,
    unread: 0,
  }
  for (const state of states) {
    const outcome = outcomeOf(state)
    if (outcome !== null) {
      outcomes[outcome] += 1
    }
  }
  const read = states.filter((state) => state.kind !== "reading").length
  return { read, outcomes }
}

/** The round Import sends (web/DESIGN.md, Patterns, Job in its card): the files whose own
 * review says they import as they are, through the profile and the options they share; none
 * until every review is read, or where no file imports. */
export function filesRequest(
  asks: readonly FileImportAsked[],
  states: readonly FileState[]
): FilesImportAsked | null {
  requireOnePerFile(asks.length, states)
  const [first] = asks
  if (first === undefined || states.some((state) => state.kind === "reading")) {
    return null
  }
  const sources = asks
    .filter((_, index) => outcomeOf(states[index]) === "imports")
    .map((ask) => ask.source)
  if (sources.length === 0) {
    return null
  }
  return {
    kind: "files",
    sources,
    profile: first.profile,
    root: first.root,
    time_zone: first.time_zone,
    differing: first.differing,
  }
}

/** The files a round left: those not sent, and those its import left out. */
export function filesLeft(
  uploads: readonly UploadedFile[],
  sent: readonly ImportSource[],
  notImported: readonly Readonly<{ upload_id: string | null }>[]
): UploadedFile[] {
  const sentIds = new Set(sent.map(uploadIdOf))
  const leftIds = new Set(notImported.map((each) => each.upload_id))
  return uploads.filter(
    (upload) => !sentIds.has(upload.id) || leftIds.has(upload.id)
  )
}

function uploadIdOf(source: ImportSource): string | null {
  return source.kind === "upload" ? source.upload_id : null
}

/** Several files' reviews and the way to read them again, as Try again and the files left
 * after a round do. */
export type FileReviews = Readonly<{
  states: readonly FileState[]
  readAgain: () => void
}>

/** The reviews of `asked`, the latest draft's, one per file, through the queue
 * (`ReviewsQueue`), at most `most` requests in flight. */
export function useFileReviews(
  asked: readonly FileImportAsked[],
  most: number
): FileReviews {
  const [readings, setReadings] = useState(0)
  const listed = useMemo(
    () =>
      asked.map((ask) => ({ key: `${readings} ${JSON.stringify(ask)}`, ask })),
    [asked, readings]
  )
  const [queue, change] = useReducer(reviewsQueued, EMPTY_REVIEWS)
  const requests = useRef(new Map<string, FileImportAsked>())
  useEffect(() => {
    requests.current = new Map<string, FileImportAsked>(
      listed.map((each) => [each.key, each.ask])
    )
    change({ kind: "listed", asks: listed.map((each) => each.key) })
  }, [listed])
  const sending = nextReview(queue, most)
  useEffect(() => {
    const request =
      sending === undefined ? undefined : requests.current.get(sending)
    if (sending === undefined || request === undefined) {
      return
    }
    change({ kind: "sent", ask: sending })
    previewOf(request).then(
      (answer) => change({ kind: "answered", ask: sending, answer }),
      (error: unknown) =>
        change({
          kind: "failed",
          ask: sending,
          error: error instanceof Error ? error : new Error(String(error)),
        })
    )
  }, [sending])
  return {
    states: fileStates(
      queue,
      listed.map((each) => each.key)
    ),
    readAgain: () => setReadings((count) => count + 1),
  }
}
