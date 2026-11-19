import { describe, expect, it } from "vitest"
import type { UploadedFile } from "@/api/imports"
import type { components } from "@/api/schema"
import { seenFile } from "./import-fixtures.test-support"
import {
  EMPTY_REVIEWS,
  type FileState,
  fileStates,
  nextReview,
  outcomeOf,
  type ReviewsChange,
  type ReviewsQueue,
  reviewsQueued,
  tallyOf,
} from "./import-reviews"
import {
  filesImporting,
  filesLeft,
  filesRequest,
  filesToDecide,
  leadAnswer,
  type ReviewedFile,
  tooManyFiles,
} from "./import-round"

type FileImportAsked = components["schemas"]["FileImportAsked"]
type ImportSource = components["schemas"]["ImportSource"]

function after(...changes: ReviewsChange[]): ReviewsQueue {
  return changes.reduce(reviewsQueued, EMPTY_REVIEWS)
}

/** A list of asks, each reading the file of its own name. */
function listed(...keys: string[]): ReviewsChange {
  return { kind: "listed", asks: keys.map((key) => ({ key, file: key })) }
}

function asked(
  uploadId: string,
  barsInBreaks: FileImportAsked["bars_in_breaks"] = "refuse",
  differing: FileImportAsked["differing"] = "refuse"
): FileImportAsked {
  return {
    kind: "file",
    source: { kind: "upload", upload_id: uploadId },
    profile: { kind: "named", name: "ninjatrader" },
    contract: null,
    root: null,
    time_zone: null,
    differing,
    bars_in_breaks: barsInBreaks,
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

const READING: FileState = { kind: "reading", last: null }

function answered(verdict: Parameters<typeof seenFile>[1]): FileState {
  return { kind: "answered", answer: seenFile("ES 03-26.Last.txt", verdict) }
}

const BREAKS = {
  left_out: false,
  bars: 60,
  breaks: ["2026-02-04"],
  breaks_total: 1,
  sessions: ["2026-02-04", "2026-02-05"],
  sessions_total: 2,
  ending_a_bar_early: [],
  ending_a_bar_early_total: 0,
  records: 2_820,
}

/** A file whose review says it imports once its bars in a break are left out (ADR-0022). */
const LEFT_OUT: FileState = {
  kind: "answered",
  answer: seenFile("ES 03-26.Last.txt", "imports", null, {
    ...BREAKS,
    left_out: true,
  }),
}

describe("outcomeOf", () => {
  it("tells a file imported without its bars in a break from one imported as it is", () => {
    expect(outcomeOf(LEFT_OUT)).toBe("imports_without_bars")
    expect(outcomeOf(answered("imports"))).toBe("imports")
  })
})

describe("the reviews' queue", () => {
  it("sends the files' reviews in their order, two at a time", () => {
    const three = after(listed("a", "b", "c"))
    const two = after(
      listed("a", "b", "c"),
      { kind: "sent", ask: "a" },
      { kind: "sent", ask: "b" }
    )
    const answer = seenFile("ES 03-26.Last.txt", "imports")

    expect(nextReview(three, 2)).toBe("a")
    expect(
      nextReview(reviewsQueued(three, { kind: "sent", ask: "a" }), 2)
    ).toBe("b")
    expect(nextReview(two, 2)).toBeUndefined()
    expect(
      nextReview(reviewsQueued(two, { kind: "answered", ask: "a", answer }), 2)
    ).toBe("c")
    expect(
      nextReview(reviewsQueued(three, { kind: "sent", ask: "a" }), 1)
    ).toBeUndefined()
  })

  it("counts a request of an older draft against the limit until it settles", () => {
    const changed = after(
      listed("a", "b"),
      { kind: "sent", ask: "a" },
      { kind: "sent", ask: "b" },
      listed("c", "d")
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
      listed("a"),
      { kind: "sent", ask: "a" },
      { kind: "failed", ask: "a", error }
    )

    expect(fileStates(failed, failed.asks)).toEqual([{ kind: "failed", error }])
    expect(nextReview(failed, 2)).toBeUndefined()
    expect(nextReview(reviewsQueued(failed, listed("a")), 2)).toBeUndefined()
    expect(nextReview(reviewsQueued(failed, listed("1 a")), 2)).toBe("1 a")
  })

  it("keeps a file's last answer in view while a change reads it again", () => {
    const answer = seenFile("ES 03-26.Last.txt", "imports")
    const changed = after(
      { kind: "listed", asks: [{ key: "0 a", file: "a" }] },
      { kind: "sent", ask: "0 a" },
      { kind: "answered", ask: "0 a", answer },
      { kind: "listed", asks: [{ key: "1 a", file: "a" }] }
    )

    expect(fileStates(changed, changed.asks)).toEqual([
      { kind: "reading", last: answer },
    ])
    expect(nextReview(changed, 2)).toBe("1 a")
  })

  it("sends again only the failed reviews when tried again", () => {
    const answer = seenFile("ES 03-26.Last.txt", "imports")
    const tried = after(
      listed("a", "b"),
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
      LEFT_OUT,
      answered("differing"),
      { kind: "answered", answer: { kind: "refused", message: "Expected." } },
      { kind: "failed", error: new Error("Gone.") },
      READING,
    ])

    expect(tally.read).toBe(6)
    expect(tally.outcomes).toEqual({
      imports: 2,
      imports_without_bars: 1,
      refused: 0,
      bars_in_breaks: 0,
      differing: 1,
      imported_before: 0,
      nothing: 0,
      unread: 2,
    })
  })
})

describe("filesRequest", () => {
  const asks = [asked("a"), asked("b"), asked("c")]

  it("asks the round of the files that import as they are, once every review is read and the others decided", () => {
    expect(
      filesRequest(
        asks,
        [answered("imports"), READING, answered("imports")],
        []
      )
    ).toBeNull()
    expect(
      filesRequest(
        asks,
        [answered("imports"), answered("refused"), answered("imports")],
        ["b"]
      )
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
      leaving_out_bars_in_breaks: [],
    })
  })

  it("waits while a file that does not import has no decision (D-105)", () => {
    for (const verdict of ["refused", "bars_in_breaks", "differing"] as const) {
      expect(
        filesRequest(
          asks,
          [answered("imports"), answered(verdict), answered("imports")],
          []
        )
      ).toBeNull()
    }
    expect(
      filesRequest(
        asks,
        [
          answered("imports"),
          { kind: "failed", error: new Error("Gone.") },
          answered("imports"),
        ],
        []
      )
    ).toBeNull()
  })

  it("sends a round beside files imported before or empty, which wait for no decision", () => {
    expect(
      filesRequest(
        asks,
        [answered("imports"), answered("imported_before"), answered("nothing")],
        []
      )
    ).toMatchObject({ sources: [{ kind: "upload", upload_id: "a" }] })
  })

  it("holds nothing back for a skipped file read again (the code review)", () => {
    expect(
      filesRequest(
        asks,
        [answered("imports"), READING, answered("imports")],
        ["b"]
      )
    ).toMatchObject({
      sources: [
        { kind: "upload", upload_id: "a" },
        { kind: "upload", upload_id: "c" },
      ],
    })
  })

  it("never sends a skipped file, though a later choice lets it import", () => {
    expect(
      filesRequest(
        asks,
        [answered("imports"), answered("imports"), answered("imports")],
        ["b"]
      )
    ).toMatchObject({
      sources: [
        { kind: "upload", upload_id: "a" },
        { kind: "upload", upload_id: "c" },
      ],
    })
  })

  it("names the files whose bars in a break are left out among those it sends", () => {
    const leaving = [
      asked("a", "leave-out"),
      asked("b", "leave-out"),
      asked("c"),
    ]

    expect(
      filesRequest(
        leaving,
        [LEFT_OUT, answered("bars_in_breaks"), answered("imports")],
        ["b"]
      )
    ).toMatchObject({
      sources: [
        { kind: "upload", upload_id: "a" },
        { kind: "upload", upload_id: "c" },
      ],
      leaving_out_bars_in_breaks: [{ kind: "upload", upload_id: "a" }],
    })
  })

  it("takes the records that differ where a file it sends was chosen to take them, and sends those files last, so that no other file of the round writes over the records they replace (the ponytail review)", () => {
    const taking = [asked("a"), asked("b", "refuse", "take-file"), asked("c")]
    const importing = [
      answered("imports"),
      answered("imports"),
      answered("imports"),
    ]

    expect(filesRequest(taking, importing, [])).toMatchObject({
      differing: "take-file",
      sources: [
        { kind: "upload", upload_id: "a" },
        { kind: "upload", upload_id: "c" },
        { kind: "upload", upload_id: "b" },
      ],
    })
    expect(filesRequest(taking, importing, ["b"])).toMatchObject({
      differing: "refuse",
    })
  })

  it("asks nothing where no file left imports as it is", () => {
    expect(
      filesRequest(
        asks,
        [
          answered("refused"),
          answered("differing"),
          { kind: "failed", error: new Error("Gone.") },
        ],
        ["a", "b", "c"]
      )
    ).toBeNull()
  })
})

describe("filesToDecide", () => {
  it("lists the files that do not import and wait for a decision, skipped ones aside", () => {
    const files: readonly ReviewedFile[] = [
      { upload: upload("a"), state: answered("imports") },
      { upload: upload("b"), state: answered("refused") },
      { upload: upload("c"), state: answered("differing") },
      {
        upload: upload("d"),
        state: { kind: "failed", error: new Error("Gone.") },
      },
      { upload: upload("e"), state: answered("imported_before") },
      { upload: upload("f"), state: answered("nothing") },
      { upload: upload("g"), state: LEFT_OUT },
      {
        upload: upload("h"),
        state: { kind: "reading", last: seenFile("h", "bars_in_breaks") },
      },
      { upload: upload("i"), state: READING },
    ]

    expect(filesToDecide(files, ["c"]).map((file) => file.upload.id)).toEqual([
      "b",
      "d",
      "h",
    ])
  })
})

describe("leadAnswer", () => {
  it("reads the round's layout against its first file not skipped, once read", () => {
    const refused = seenFile("ES a.Last.txt", "refused")
    const imports = seenFile("ES b.Last.txt", "imports")
    const files: readonly ReviewedFile[] = [
      { upload: upload("a"), state: { kind: "answered", answer: refused } },
      { upload: upload("b"), state: { kind: "answered", answer: imports } },
    ]

    expect(leadAnswer(files, [])).toBe(refused)
    expect(leadAnswer(files, ["a"])).toBe(imports)
    expect(leadAnswer(files, ["a", "b"])).toBeNull()
    expect(leadAnswer([{ upload: upload("a"), state: READING }], [])).toBeNull()
  })
})

describe("filesImporting", () => {
  it("counts the files Import sends, by their last review while they are read again, skipped ones aside", () => {
    const answer = seenFile("ES 03-26.Last.txt", "imports")
    const files: readonly ReviewedFile[] = [
      { upload: upload("a"), state: { kind: "reading", last: answer } },
      { upload: upload("b"), state: answered("imports") },
      { upload: upload("c"), state: LEFT_OUT },
      { upload: upload("d"), state: answered("differing") },
      { upload: upload("e"), state: READING },
    ]

    expect(filesImporting(files, [])).toBe(3)
    expect(filesImporting(files, ["b"])).toBe(2)
    expect(
      filesImporting([{ upload: upload("a"), state: answered("refused") }], [])
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
