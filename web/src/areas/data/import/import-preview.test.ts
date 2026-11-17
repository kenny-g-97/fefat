import { describe, expect, it } from "vitest"
import type { ImportPreviewAnswer } from "@/api/imports"
import {
  EMPTY_QUEUE,
  type PreviewQueue,
  previewState,
  type QueueChange,
  queued,
  toSend,
} from "./import-preview"

const ANSWER: ImportPreviewAnswer = {
  kind: "refused",
  message: "Expected a file.",
}

function after(...changes: QueueChange[]): PreviewQueue {
  return changes.reduce(queued, EMPTY_QUEUE)
}

describe("the preview's queue", () => {
  it("sends one ask at a time, and the latest one after it", () => {
    const busy = after({ kind: "asked", ask: "a" }, { kind: "sent", ask: "a" })
    const meanwhile = after(
      { kind: "asked", ask: "a" },
      { kind: "sent", ask: "a" },
      { kind: "asked", ask: "b" },
      { kind: "asked", ask: "c" }
    )

    expect(toSend(after({ kind: "asked", ask: "a" }))).toBe("a")
    expect(toSend(busy)).toBeNull()
    expect(toSend(meanwhile)).toBeNull()
    expect(
      toSend(queued(meanwhile, { kind: "answered", ask: "a", answer: ANSWER }))
    ).toBe("c")
  })

  it("keeps the last answer while a newer ask is read", () => {
    const answered = after(
      { kind: "asked", ask: "a" },
      { kind: "sent", ask: "a" },
      { kind: "answered", ask: "a", answer: ANSWER },
      { kind: "asked", ask: "b" },
      { kind: "sent", ask: "b" }
    )

    expect(answered.answered).toEqual({ ask: "a", answer: ANSWER })
    expect(answered.inFlight).toBe("b")
  })

  it("changes nothing for an ask it holds, waiting, in flight, or settled", () => {
    const waiting = after({ kind: "asked", ask: "a" })
    const flying = queued(waiting, { kind: "sent", ask: "a" })
    const settled = queued(flying, {
      kind: "failed",
      ask: "a",
      error: new Error("no"),
    })

    expect(queued(waiting, { kind: "asked", ask: "a" })).toBe(waiting)
    expect(queued(flying, { kind: "asked", ask: "a" })).toBe(flying)
    expect(queued(settled, { kind: "asked", ask: "a" })).toBe(settled)
    expect(toSend(settled)).toBeNull()
  })

  it("sends a failed ask again once another ask was answered between", () => {
    const back = after(
      { kind: "asked", ask: "a" },
      { kind: "sent", ask: "a" },
      { kind: "failed", ask: "a", error: new Error("no") },
      { kind: "asked", ask: "b" },
      { kind: "sent", ask: "b" },
      { kind: "answered", ask: "b", answer: ANSWER },
      { kind: "asked", ask: "a" }
    )

    expect(back.failed).toBeNull()
    expect(toSend(back)).toBe("a")
  })

  it("shows an older answer as not the latest's, and the latest's failure", () => {
    const answered = after(
      { kind: "asked", ask: "a" },
      { kind: "sent", ask: "a" },
      { kind: "answered", ask: "a", answer: ANSWER },
      { kind: "asked", ask: "b" },
      { kind: "sent", ask: "b" },
      { kind: "failed", ask: "b", error: new Error("no") }
    )

    expect(previewState(answered, "a")).toEqual({
      answer: ANSWER,
      current: true,
      reading: false,
      error: null,
    })
    expect(previewState(answered, "b")).toMatchObject({
      answer: ANSWER,
      current: false,
      error: new Error("no"),
    })
  })

  it("sends an earlier ask again once a later one was asked between", () => {
    const back = after(
      { kind: "asked", ask: "a" },
      { kind: "sent", ask: "a" },
      { kind: "answered", ask: "a", answer: ANSWER },
      { kind: "asked", ask: "b" },
      { kind: "sent", ask: "b" },
      { kind: "answered", ask: "b", answer: ANSWER },
      { kind: "asked", ask: "a" }
    )

    expect(toSend(back)).toBe("a")
  })
})
