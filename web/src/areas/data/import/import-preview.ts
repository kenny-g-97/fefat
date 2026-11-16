import { useEffect, useReducer, useRef, useState } from "react"
import {
  type ImportPreviewAnswer,
  type PreviewAsked,
  previewOf,
} from "@/api/imports"

/** A preview's queue (web/DESIGN.md, Patterns, Live draft): one request in flight, since each
 * starts a runner of the server's that reads the whole file, and the latest draft's next; the
 * last answer stays while a newer one is read, and a failure is kept for the ask it failed until
 * an answer comes. Each ask is its request's JSON after the number of times the page asked to
 * read again, which tells two asks apart. */
export type PreviewQueue = Readonly<{
  inFlight: string | null
  next: string | null
  answered: Readonly<{ ask: string; answer: ImportPreviewAnswer }> | null
  failed: Readonly<{ ask: string; error: Error }> | null
}>

export const EMPTY_QUEUE: PreviewQueue = {
  inFlight: null,
  next: null,
  answered: null,
  failed: null,
}

export type QueueChange =
  | Readonly<{ kind: "asked"; ask: string }>
  | Readonly<{ kind: "answered"; ask: string; answer: ImportPreviewAnswer }>
  | Readonly<{ kind: "failed"; ask: string; error: Error }>
  | Readonly<{ kind: "sent"; ask: string }>

/** The queue after `change`; `toSend` says which ask goes to the server next, if any. */
export function queued(queue: PreviewQueue, change: QueueChange): PreviewQueue {
  switch (change.kind) {
    case "asked":
      return knows(queue, change.ask) ? queue : { ...queue, next: change.ask }
    case "sent":
      return {
        ...queue,
        inFlight: change.ask,
        next: queue.next === change.ask ? null : queue.next,
      }
    case "answered":
      return {
        ...queue,
        inFlight: null,
        answered: { ask: change.ask, answer: change.answer },
        failed: null,
      }
    case "failed":
      return {
        ...queue,
        inFlight: null,
        failed: { ask: change.ask, error: change.error },
      }
  }
}

/** Whether `ask` is the latest the queue holds already, waiting, in flight, or settled, so
 * that the same ask made again, as by a page drawn again, changes nothing. */
function knows(queue: PreviewQueue, ask: string): boolean {
  if (queue.next !== null) {
    return queue.next === ask
  }
  return (
    queue.inFlight === ask ||
    (queue.inFlight === null &&
      (queue.answered?.ask === ask || queue.failed?.ask === ask))
  )
}

/** The ask to send now: the latest, once nothing is in flight, unless it was answered or
 * failed already. */
export function toSend(queue: PreviewQueue): string | null {
  const next = queue.next
  if (queue.inFlight !== null || next === null) {
    return null
  }
  const settled = queue.answered?.ask === next || queue.failed?.ask === next
  return settled ? null : next
}

/** What the queue shows of the latest ask: its answer once read, else the last answer, marked
 * as not the latest's, and whether one is being read; the latest's failure, if it failed. */
export type PreviewState = Readonly<{
  answer: ImportPreviewAnswer | null
  current: boolean
  reading: boolean
  error: Error | null
}>

export function previewState(
  queue: PreviewQueue,
  ask: string | null
): PreviewState {
  return {
    answer: queue.answered?.answer ?? null,
    current: ask !== null && queue.answered?.ask === ask,
    reading: queue.inFlight !== null || toSend(queue) !== null,
    error:
      ask !== null && queue.failed?.ask === ask ? queue.failed.error : null,
  }
}

/** The preview of a draft's latest ask, and the way to read it again, as Try again does after
 * a failure. */
export type LatestPreview = PreviewState & Readonly<{ readAgain: () => void }>

/** The preview of `asked`, the latest of a draft, through the queue (`PreviewQueue`). */
export function useLatestPreview(asked: PreviewAsked | null): LatestPreview {
  const [readings, setReadings] = useState(0)
  const ask = asked === null ? null : `${readings} ${JSON.stringify(asked)}`
  const [queue, change] = useReducer(queued, EMPTY_QUEUE)
  const asks = useRef(new Map<string, PreviewAsked>())
  useEffect(() => {
    if (ask !== null && asked !== null) {
      asks.current.set(ask, asked)
      change({ kind: "asked", ask })
    }
  }, [ask, asked])
  const sending = toSend(queue)
  useEffect(() => {
    const request = sending === null ? undefined : asks.current.get(sending)
    if (sending === null || request === undefined) {
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
    ...previewState(queue, ask),
    readAgain: () => setReadings((count) => count + 1),
  }
}
