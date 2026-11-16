import { useEffect, useMemo, useReducer, useRef, useState } from "react"
import type { ImportPreviewAnswer, UploadedFile } from "@/api/imports"
import type { components } from "@/api/schema"
import { previewSent } from "./import-preview"

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

/** A file's review in the round's list: being read, with the file's last answer while it is
 * read again after a change, or settled. */
export type FileState =
  | Readonly<{ kind: "reading"; last: ImportPreviewAnswer | null }>
  | Settled

/** An ask of the list: its request's JSON after the number of times the page asked to read
 * again, and the file it reads, an upload's id or a path. */
export type ListedAsk = Readonly<{ key: string; file: string }>

/** Several files' reviews (web/DESIGN.md, Patterns, Live draft): the latest draft's asks, one
 * per file in the files' order; the requests in flight, an older draft's among them, since each
 * holds a runner of the server's until it settles; the latest asks' answers and failures; and
 * each listed file's last answer, which stays in view while the file is read again. */
export type ReviewsQueue = Readonly<{
  asks: readonly ListedAsk[]
  inFlight: readonly string[]
  settled: ReadonlyMap<string, Settled>
  last: ReadonlyMap<string, ImportPreviewAnswer>
}>

export const EMPTY_REVIEWS: ReviewsQueue = {
  asks: [],
  inFlight: [],
  settled: new Map(),
  last: new Map(),
}

export type ReviewsChange =
  | Readonly<{ kind: "listed"; asks: readonly ListedAsk[] }>
  | Readonly<{ kind: "sent"; ask: string }>
  | Readonly<{ kind: "answered"; ask: string; answer: ImportPreviewAnswer }>
  | Readonly<{ kind: "failed"; ask: string; error: Error }>
  | Readonly<{ kind: "retried" }>

/** The queue after `change`: a new list keeps the answers of the asks it still holds and the
 * last answers of the files it still lists, an answer to an ask no longer listed only frees
 * its place, and Try again forgets the failures, so that only their asks go again. */
export function reviewsQueued(
  queue: ReviewsQueue,
  change: ReviewsChange
): ReviewsQueue {
  switch (change.kind) {
    case "listed": {
      const keys = new Set(change.asks.map((each) => each.key))
      const files = new Set(change.asks.map((each) => each.file))
      return {
        ...queue,
        asks: change.asks,
        settled: new Map([...queue.settled].filter(([ask]) => keys.has(ask))),
        last: new Map([...queue.last].filter(([file]) => files.has(file))),
      }
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
    case "retried": {
      const answered = [...queue.settled].filter(
        ([, settled]) => settled.kind === "answered"
      )
      return { ...queue, settled: new Map(answered) }
    }
  }
}

function settledBy(
  queue: ReviewsQueue,
  ask: string,
  settled: Settled
): ReviewsQueue {
  const inFlight = queue.inFlight.filter((each) => each !== ask)
  const listed = queue.asks.find((each) => each.key === ask)
  if (listed === undefined) {
    return { ...queue, inFlight }
  }
  const last =
    settled.kind === "answered"
      ? new Map(queue.last).set(listed.file, settled.answer)
      : queue.last
  return {
    ...queue,
    inFlight,
    settled: new Map(queue.settled).set(ask, settled),
    last,
  }
}

/** The next ask to send, the first not read yet in the files' order, while fewer than `most`
 * requests are in flight; a failed one is settled and goes again only when tried again. */
export function nextReview(
  queue: ReviewsQueue,
  most: number
): string | undefined {
  if (queue.inFlight.length >= most) {
    return undefined
  }
  return queue.asks.find(
    ({ key }) => !queue.inFlight.includes(key) && !queue.settled.has(key)
  )?.key
}

/** The review of each of `asks`, in their order: being read, with its file's last answer,
 * until it settles. */
export function fileStates(
  queue: ReviewsQueue,
  asks: readonly ListedAsk[]
): readonly FileState[] {
  return asks.map(
    ({ key, file }) =>
      queue.settled.get(key) ?? {
        kind: "reading",
        last: queue.last.get(file) ?? null,
      }
  )
}

/** What a file's row shows: its review, or while it is read again, its last answer. */
export function shownState(state: FileState): FileState {
  return state.kind === "reading" && state.last !== null
    ? { kind: "answered", answer: state.last }
    : state
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

/** How many files Import sends, by each file's review or, while it is read again, its last
 * one, so that Import's name holds still through a change; none where none imports. */
export function filesImporting(states: readonly FileState[]): number | null {
  const count = states.filter(
    (state) => outcomeOf(shownState(state)) === "imports"
  ).length
  return count === 0 ? null : count
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

/** The files a round left: those its import left out, and those not sent that hold records
 * to import, refused, differing, or not read, rather than imported before or empty. */
export function filesLeft(
  files: readonly ReviewedFile[],
  sent: readonly ImportSource[],
  notImported: readonly Readonly<{ upload_id: string | null }>[]
): UploadedFile[] {
  const sentIds = new Set(sent.map(uploadIdOf))
  const leftIds = new Set(notImported.map((each) => each.upload_id))
  return files
    .filter(({ upload, state }) =>
      sentIds.has(upload.id) ? leftIds.has(upload.id) : !doneWith(state)
    )
    .map(({ upload }) => upload)
}

function doneWith(state: FileState): boolean {
  const outcome = outcomeOf(state)
  return outcome === "imported_before" || outcome === "nothing"
}

/** Why `count` files are too many for one import, before any is copied; none where they are
 * not. */
export function tooManyFiles(count: number): string | null {
  return count > FILES_AT_MOST
    ? `Expected ${FILES_AT_MOST} files at most in one import, got ${count}: choose fewer, and import the others next.`
    : null
}

function uploadIdOf(source: ImportSource): string | null {
  return source.kind === "upload" ? source.upload_id : null
}

/** The file `source` names, by its upload's id or its path. */
function fileOf(source: ImportSource): string {
  return source.kind === "upload" ? source.upload_id : source.path
}

/** Several files' reviews, the way to read the failed ones again, as Try again does, and to
 * read them all again, as the files left after a round are. */
export type FileReviews = Readonly<{
  states: readonly FileState[]
  tryAgain: () => void
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
      asked.map((ask) => ({
        key: `${readings} ${JSON.stringify(ask)}`,
        file: fileOf(ask.source),
        ask,
      })),
    [asked, readings]
  )
  const [queue, change] = useReducer(reviewsQueued, EMPTY_REVIEWS)
  const requests = useRef(new Map<string, FileImportAsked>())
  useEffect(() => {
    requests.current = new Map<string, FileImportAsked>(
      listed.map((each) => [each.key, each.ask])
    )
    change({
      kind: "listed",
      asks: listed.map(({ key, file }) => ({ key, file })),
    })
  }, [listed])
  const sending = nextReview(queue, most)
  useEffect(() => {
    const request =
      sending === undefined ? undefined : requests.current.get(sending)
    if (sending === undefined || request === undefined) {
      return
    }
    change({ kind: "sent", ask: sending })
    previewSent(sending, request, change)
  }, [sending])
  return {
    states: fileStates(queue, listed),
    tryAgain: () => change({ kind: "retried" }),
    readAgain: () => setReadings((count) => count + 1),
  }
}
