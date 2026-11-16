import { describe, expect, it } from "vitest"
import type { UploadedFile } from "@/api/imports"
import type { components } from "@/api/schema"
import { seenFile } from "./import-fixtures.test-support"
import {
  EMPTY_REVIEWS,
  type FileState,
  filesLeft,
  filesRequest,
  fileStates,
  nextReview,
  type ReviewedFile,
  type ReviewsChange,
  type ReviewsQueue,
  reviewsQueued,
  tallyOf,
  tooManyFiles,
} from "./import-reviews"

type FileImportAsked = components["schemas"]["FileImportAsked"]
type ImportSource = components["schemas"]["ImportSource"]

function after(...changes: ReviewsChange[]): ReviewsQueue {
  return changes.reduce(reviewsQueued, EMPTY_REVIEWS)
}

function asked(uploadId: string): FileImportAsked {
  return {
    kind: "file",
    source: { kind: "upload", upload_id: uploadId },
    profile: { kind: "named", name: "ninjatrader" },
    contract: null,
    root: null,
    time_zone: null,
    differing: "refuse",
  }
}

function upload(id: string): UploadedFile {
  return {
    id,
    name: `ES ${id}.Last.txt`,
    size: 42,
    sha256: "0".repeat(64),
    uploaded_at: "2026-11-16T10:00:00Z",
  }
}

const READING: FileState = { kind: "reading" }

function answered(verdict: Parameters<typeof seenFile>[1]): FileState {
  return { kind: "answered", answer: seenFile("ES 03-26.Last.txt", verdict) }
}

describe("the reviews' queue", () => {
  it("sends the files' reviews in their order, two at a time", () => {
    const listed = after({ kind: "listed", asks: ["a", "b", "c"] })
    const two = after(
      { kind: "listed", asks: ["a", "b", "c"] },
      { kind: "sent", ask: "a" },
      { kind: "sent", ask: "b" }
    )
    const answer = seenFile("ES 03-26.Last.txt", "imports")

    expect(nextReview(listed, 2)).toBe("a")
    expect(
      nextReview(reviewsQueued(listed, { kind: "sent", ask: "a" }), 2)
    ).toBe("b")
    expect(nextReview(two, 2)).toBeUndefined()
    expect(
      nextReview(reviewsQueued(two, { kind: "answered", ask: "a", answer }), 2)
    ).toBe("c")
    expect(
      nextReview(reviewsQueued(listed, { kind: "sent", ask: "a" }), 1)
    ).toBeUndefined()
  })

  it("counts a request of an older draft against the limit until it settles", () => {
    const changed = after(
      { kind: "listed", asks: ["a", "b"] },
      { kind: "sent", ask: "a" },
      { kind: "sent", ask: "b" },
      { kind: "listed", asks: ["c", "d"] }
    )
    const answer = seenFile("ES 03-26.Last.txt", "imports")
    const settled = reviewsQueued(changed, {
      kind: "answered",
      ask: "a",
      answer,
    })

    expect(nextReview(changed, 2)).toBeUndefined()
    expect(nextReview(settled, 2)).toBe("c")
    expect(fileStates(settled, settled.asks)).toEqual([READING, READING])
  })

  it("settles a failed review, which only a new reading sends again", () => {
    const error = new Error("The server is not answering.")
    const failed = after(
      { kind: "listed", asks: ["a"] },
      { kind: "sent", ask: "a" },
      { kind: "failed", ask: "a", error }
    )

    expect(fileStates(failed, failed.asks)).toEqual([{ kind: "failed", error }])
    expect(nextReview(failed, 2)).toBeUndefined()
    expect(
      nextReview(reviewsQueued(failed, { kind: "listed", asks: ["a"] }), 2)
    ).toBeUndefined()
    expect(
      nextReview(reviewsQueued(failed, { kind: "listed", asks: ["1 a"] }), 2)
    ).toBe("1 a")
  })

  it("sends again only the failed reviews when tried again", () => {
    const answer = seenFile("ES 03-26.Last.txt", "imports")
    const tried = after(
      { kind: "listed", asks: ["a", "b"] },
      { kind: "sent", ask: "a" },
      { kind: "sent", ask: "b" },
      { kind: "answered", ask: "a", answer },
      { kind: "failed", ask: "b", error: new Error("Gone.") },
      { kind: "retried" }
    )

    expect(fileStates(tried, tried.asks)).toEqual([
      { kind: "answered", answer },
      READING,
    ])
    expect(nextReview(tried, 2)).toBe("b")
  })
})

describe("tallyOf", () => {
  it("counts the files read by what their import would do", () => {
    const tally = tallyOf([
      answered("imports"),
      answered("imports"),
      answered("differing"),
      { kind: "answered", answer: { kind: "refused", message: "Expected." } },
      { kind: "failed", error: new Error("Gone.") },
      READING,
    ])

    expect(tally.read).toBe(5)
    expect(tally.outcomes).toEqual({
      imports: 2,
      refused: 0,
      differing: 1,
      imported_before: 0,
      nothing: 0,
      unread: 2,
    })
  })
})

describe("filesRequest", () => {
  const asks = [asked("a"), asked("b"), asked("c")]

  it("asks the round of the files that import as they are, once every review is read", () => {
    expect(
      filesRequest(asks, [answered("imports"), READING, answered("imports")])
    ).toBeNull()
    expect(
      filesRequest(asks, [
        answered("imports"),
        answered("refused"),
        answered("imports"),
      ])
    ).toEqual({
      kind: "files",
      sources: [
        { kind: "upload", upload_id: "a" },
        { kind: "upload", upload_id: "c" },
      ],
      profile: { kind: "named", name: "ninjatrader" },
      root: null,
      time_zone: null,
      differing: "refuse",
    })
  })

  it("asks nothing where no file imports as it is", () => {
    expect(
      filesRequest(asks, [
        answered("refused"),
        answered("differing"),
        { kind: "failed", error: new Error("Gone.") },
      ])
    ).toBeNull()
  })
})

describe("filesLeft", () => {
  it("leaves the files the round left out and those not sent that have records to import", () => {
    const files: readonly ReviewedFile[] = [
      { upload: upload("a"), state: answered("imports") },
      { upload: upload("b"), state: answered("imports") },
      { upload: upload("c"), state: answered("differing") },
      { upload: upload("d"), state: answered("imports") },
      { upload: upload("e"), state: answered("imported_before") },
      { upload: upload("f"), state: answered("nothing") },
    ]
    const sent: readonly ImportSource[] = [
      { kind: "upload", upload_id: "a" },
      { kind: "upload", upload_id: "b" },
      { kind: "upload", upload_id: "d" },
    ]

    expect(filesLeft(files, sent, [{ upload_id: "b" }])).toEqual([
      upload("b"),
      upload("c"),
    ])
  })
})

describe("tooManyFiles", () => {
  it("refuses more files than one import takes, before any is copied", () => {
    expect(tooManyFiles(200)).toBeNull()
    expect(tooManyFiles(201)).toBe(
      "Expected 200 files at most in one import, got 201: choose fewer, and import the others next."
    )
  })
})
