import { describe, expect, it } from "vitest"
import type { ImportAsked, UploadedFile } from "@/api/imports"
import type { components } from "@/api/schema"
import {
  type Draft,
  drafted,
  NEW_INSTRUMENT,
  startingDraft,
} from "./import-draft"
import {
  LISTED,
  NINJATRADER,
  NINJATRADER_TABLE,
  seenFile,
} from "./import-fixtures.test-support"
import { asksOf } from "./import-request"
import type { FileState, ReviewedFile } from "./import-reviews"
import {
  importWaits,
  type ReviewFacts,
  type ReviewStanding,
  reviewStanding,
  shownStep,
  stepAfter,
  stepBefore,
  stepStates,
} from "./import-steps"

type OffsetSeen = components["schemas"]["OffsetSeen"]

function uploaded(id: string, name: string): UploadedFile {
  return {
    id,
    name,
    size: 42,
    sha256: "0".repeat(64),
    uploaded_at: "2026-11-18T10:00:00Z",
  }
}

const MARCH = uploaded(
  "0193a000-0000-7000-8000-000000000001",
  "XES 03-26.Last.txt"
)
const JUNE = uploaded(
  "0193a000-0000-7000-8000-000000000002",
  "XES 06-26.Last.txt"
)
const EMPTY = startingDraft({ kind: "none" })
const CHOSEN = drafted(EMPTY, {
  kind: "source",
  source: { kind: "uploads", uploads: [MARCH] },
})
const TWO = drafted(EMPTY, {
  kind: "source",
  source: { kind: "uploads", uploads: [MARCH, JUNE] },
})
const LISTED_ONE = drafted(CHOSEN, {
  kind: "listed profile",
  name: "ninjatrader",
})
const ROUND = drafted(TWO, { kind: "listed profile", name: "ninjatrader" })
const PRESET = startingDraft({ kind: "profile", name: "ninjatrader" })
const BATCH = startingDraft({ kind: "batch" })

const WAITING: ReviewStanding = { kind: "waiting" }
const READING: ReviewStanding = { kind: "reading", again: false }
const REFUSED: ReviewStanding = { kind: "not importing", outcome: "refused" }

function late(cause: OffsetSeen["cause"]): OffsetSeen {
  return {
    cause,
    direction: "late",
    duration: "6 hours",
    first_trade_date: "2026-02-02",
    last_trade_date: "2026-02-06",
    description: "Records 6 hours late.",
  }
}

function statesOf(
  draft: Draft,
  review: ReviewStanding,
  offsets: readonly OffsetSeen[] = []
) {
  return stepStates({
    draft,
    asks: asksOf(draft, LISTED, NINJATRADER_TABLE),
    profiles: LISTED,
    offsets,
    review,
  })
}

function waits(
  draft: Draft,
  review: ReviewStanding,
  offsets: readonly OffsetSeen[] = []
) {
  return importWaits(statesOf(draft, review, offsets), review, draft)
}

describe("stepStates", () => {
  it("marks every step of an empty draft incomplete, each saying what it needs", () => {
    expect(statesOf(EMPTY, WAITING)).toEqual({
      file: {
        kind: "incomplete",
        line: "Choose files, or type a path",
        alert: false,
      },
      layout: {
        kind: "incomplete",
        line: "Choose a profile, or make one",
        alert: false,
      },
      instrument: {
        kind: "incomplete",
        line: "Waits for Layout",
        alert: false,
      },
      review: { kind: "incomplete", line: "Waits for 3 steps", alert: false },
    })
  })

  it("completes Layout and Instrument from a preset in the address, before any file", () => {
    const states = statesOf(PRESET, WAITING)

    expect(states.file.kind).toBe("incomplete")
    expect(states.layout).toEqual({ kind: "complete", line: "ninjatrader" })
    expect(states.instrument).toEqual({
      kind: "complete",
      line: "From the file's name",
    })
    expect(states.review).toEqual({
      kind: "incomplete",
      line: "Waits for File",
      alert: false,
    })
  })

  it("marks File complete once files are chosen, before their table is read", () => {
    expect(statesOf(CHOSEN, WAITING).file).toEqual({
      kind: "complete",
      line: "XES 03-26.Last.txt",
    })
    expect(statesOf(TWO, WAITING).file).toEqual({
      kind: "complete",
      line: "2 files",
    })
  })

  it("says what a new profile misses under Layout, and its name once it misses nothing", () => {
    const made = drafted(CHOSEN, { kind: "new profile", base: NINJATRADER })
    const unread = drafted(made, {
      kind: "profile fields",
      fields: {
        roles: {
          kind: "chosen",
          roles: ["timestamp", "open", "high", "low", "close", "unused"],
        },
      },
    })
    const nameless = drafted(made, {
      kind: "profile fields",
      fields: { name: "", provider: "" },
    })

    expect(statesOf(unread, WAITING).layout).toEqual({
      kind: "incomplete",
      line: "Choose the column of the volume",
      alert: false,
    })
    expect(statesOf(nameless, WAITING).layout.line).toBe("2 things to give")
    expect(statesOf(made, READING).layout).toEqual({
      kind: "complete",
      line: "my-ninjatrader, new",
    })
  })

  it("says what a new instrument misses under Instrument, and its root once it misses nothing", () => {
    const made = drafted(CHOSEN, { kind: "new profile", base: NINJATRADER })
    const untick = drafted(made, {
      kind: "instrument",
      instrument: {
        kind: "new",
        fields: {
          ...NEW_INSTRUMENT,
          root: "XES",
          pointValue: "50",
          firstTradeDate: "2010-01-04",
        },
      },
    })
    const ticked = drafted(untick, {
      kind: "instrument fields",
      fields: { tickSize: "0.25" },
    })

    expect(statesOf(untick, WAITING).instrument).toEqual({
      kind: "incomplete",
      line: "Give its tick size",
      alert: false,
    })
    expect(statesOf(untick, WAITING).layout.kind).toBe("complete")
    expect(statesOf(ticked, READING).instrument).toEqual({
      kind: "complete",
      line: "XES, new",
    })
  })

  it("names the instrument a listed profile carries, or the contract typed", () => {
    const carrying = [
      ...LISTED,
      {
        origin: "saved" as const,
        profile: { ...NINJATRADER, name: "es-minutes", instrument: "ES" },
      },
    ]
    const draft = drafted(CHOSEN, {
      kind: "listed profile",
      name: "es-minutes",
    })
    const typed = drafted(LISTED_ONE, {
      kind: "contract",
      contract: "XESH2026",
    })
    const states = stepStates({
      draft,
      asks: asksOf(draft, carrying, null),
      profiles: carrying,
      offsets: [],
      review: READING,
    })

    expect(states.instrument).toEqual({ kind: "complete", line: "ES" })
    expect(statesOf(typed, READING).instrument.line).toBe("XESH2026")
    expect(statesOf(ROUND, READING).instrument.line).toBe(
      "From each file's name"
    )
  })

  it("needs no Layout and no Instrument for a Databento batch", () => {
    expect(statesOf(BATCH, WAITING)).toEqual({
      file: {
        kind: "incomplete",
        line: "Type the path of the batch's folder",
        alert: false,
      },
      layout: { kind: "not needed", line: "Not needed for a batch" },
      instrument: { kind: "not needed", line: "Not needed for a batch" },
      review: { kind: "incomplete", line: "Waits for File", alert: false },
    })
    const typed = drafted(BATCH, {
      kind: "source",
      source: { kind: "path", path: "D:/batches/GLBX-1/" },
    })
    expect(statesOf(typed, READING).file).toEqual({
      kind: "complete",
      line: "GLBX-1",
    })
  })

  it("takes Layout's check away for an offset of the review that points at it, as an alert", () => {
    const states = statesOf(LISTED_ONE, REFUSED, [late("time-zone")])

    expect(states.layout).toEqual({
      kind: "incomplete",
      line: "Check the time zone",
      alert: true,
    })
    expect(states.review).toEqual({
      kind: "incomplete",
      line: "Refused",
      alert: false,
    })
    expect(
      statesOf(LISTED_ONE, REFUSED, [late("bar-stamping")]).layout.line
    ).toBe("Check the bar's timestamp")
    expect(
      statesOf(LISTED_ONE, REFUSED, [late("time-zone-or-bar-stamping")]).layout
        .line
    ).toBe("Check the time zone")
  })

  it("says what the review waits for, then what Import sends", () => {
    const line = (review: ReviewStanding) => statesOf(ROUND, review).review

    expect(statesOf(LISTED_ONE, READING).review.line).toBe("Reading the file")
    expect(line(READING).line).toBe("Reading the files")
    expect(line({ kind: "to decide", files: 3 }).line).toBe(
      "3 files wait for your decision"
    )
    expect(line({ kind: "to decide", files: 1 }).line).toBe(
      "1 file waits for your decision"
    )
    expect(line({ kind: "nothing to send" }).line).toBe("No file to import")
    expect(statesOf(LISTED_ONE, { kind: "ready", files: null }).review).toEqual(
      {
        kind: "complete",
        line: "Ready to import",
      }
    )
    expect(line({ kind: "ready", files: 29 })).toEqual({
      kind: "complete",
      line: "29 files to import",
    })
    expect(line({ kind: "imported" })).toEqual({
      kind: "complete",
      line: "Imported",
    })
  })
})

describe("stepAfter and stepBefore", () => {
  it("walk the four steps of a file, and pass over Layout and Instrument for a batch", () => {
    expect(stepAfter("file", CHOSEN)).toBe("layout")
    expect(stepAfter("instrument", CHOSEN)).toBe("review")
    expect(stepAfter("review", CHOSEN)).toBeNull()
    expect(stepBefore("file", CHOSEN)).toBeNull()
    expect(stepBefore("layout", CHOSEN)).toBe("file")
    expect(stepBefore("review", CHOSEN)).toBe("instrument")
    expect(stepAfter("file", BATCH)).toBe("review")
    expect(stepBefore("review", BATCH)).toBe("file")
  })
})

describe("shownStep", () => {
  it("shows File for no step, or for one the draft does not need", () => {
    const switched = drafted(CHOSEN, { kind: "reading", reading: "batch" })

    expect(shownStep(undefined, CHOSEN)).toBe("file")
    expect(shownStep("layout", CHOSEN)).toBe("layout")
    expect(shownStep("layout", switched)).toBe("file")
    expect(shownStep("instrument", switched)).toBe("file")
    expect(shownStep("review", switched)).toBe("review")
  })
})

describe("importWaits", () => {
  it("names the steps still to complete first", () => {
    expect(waits(EMPTY, WAITING)).toBe(
      "Complete File, Layout, and Instrument first"
    )
    expect(waits(PRESET, WAITING)).toBe("Complete File first")
    expect(waits(LISTED_ONE, REFUSED, [late("time-zone")])).toBe(
      "Complete Layout first"
    )
    expect(waits(BATCH, WAITING)).toBe("Complete File first")
  })

  it("says that a read is in progress, the first or a change's", () => {
    expect(waits(LISTED_ONE, READING)).toBe(
      "Reading the file against your data"
    )
    expect(waits(ROUND, READING)).toBe("Reading the files against your data")
    expect(waits(ROUND, { kind: "reading", again: true })).toBe(
      "Reading your latest change"
    )
  })

  it("counts the files that wait for a decision", () => {
    expect(waits(ROUND, { kind: "to decide", files: 3 })).toBe(
      "Decide what to do with 3 files first"
    )
    expect(waits(ROUND, { kind: "to decide", files: 1 })).toBe(
      "Decide what to do with 1 file first"
    )
  })

  it("gives one file's or a batch's verdict, and that a round has no file to send", () => {
    const typed = drafted(BATCH, {
      kind: "source",
      source: { kind: "path", path: "D:/batches/GLBX-1" },
    })

    expect(waits(LISTED_ONE, REFUSED)).toBe("It would be refused")
    expect(
      waits(LISTED_ONE, { kind: "not importing", outcome: "imported_before" })
    ).toBe("It is imported already: importing it again changes nothing")
    expect(
      waits(LISTED_ONE, { kind: "not importing", outcome: "unread" })
    ).toBe("The file could not be read")
    expect(waits(typed, { kind: "not importing", outcome: "unread" })).toBe(
      "The batch could not be read"
    )
    expect(waits(ROUND, { kind: "nothing to send" })).toBe("No file to import")
  })

  it("says nothing once Import has something to send, or wrote", () => {
    expect(waits(LISTED_ONE, { kind: "ready", files: null })).toBeNull()
    expect(waits(ROUND, { kind: "imported" })).toBeNull()
  })
})

describe("reviewStanding", () => {
  const unasked: ReviewFacts["review"] = {
    answer: null,
    current: false,
    reading: false,
    error: null,
  }
  const asks = asksOf(LISTED_ONE, LISTED, null)
  const one = (
    review: ReviewFacts["review"],
    request: ImportAsked | null = null
  ) =>
    reviewStanding({
      asks,
      request,
      imported: false,
      review,
      files: [],
      skipped: [],
    })

  it("waits while the steps before the review miss something", () => {
    expect(
      reviewStanding({
        asks: asksOf(EMPTY, LISTED, null),
        request: null,
        imported: false,
        review: unasked,
        files: [],
        skipped: [],
      })
    ).toEqual({ kind: "waiting" })
  })

  it("reads one file's review, then gives its verdict, or Import's request", () => {
    const answered = (verdict: Parameters<typeof seenFile>[1]) => ({
      answer: seenFile("XES 03-26.Last.txt", verdict),
      current: true,
      reading: false,
      error: null,
    })

    expect(one({ ...unasked, reading: true })).toEqual({
      kind: "reading",
      again: false,
    })
    expect(
      one({ ...answered("refused"), current: false, reading: true })
    ).toEqual({ kind: "reading", again: true })
    expect(one(answered("refused"))).toEqual({
      kind: "not importing",
      outcome: "refused",
    })
    expect(one(answered("differing"))).toEqual({
      kind: "not importing",
      outcome: "differing",
    })
    expect(one({ ...unasked, error: new Error("Gone.") })).toEqual({
      kind: "not importing",
      outcome: "unread",
    })
    expect(
      one({
        ...unasked,
        answer: { kind: "refused", message: "Expected a file." },
        current: true,
      })
    ).toEqual({ kind: "not importing", outcome: "unread" })
    expect(one(answered("imports"), asks.review)).toEqual({
      kind: "ready",
      files: null,
    })
    expect(
      reviewStanding({
        asks,
        request: asks.review,
        imported: true,
        review: answered("imports"),
        files: [],
        skipped: [],
      })
    ).toEqual({ kind: "imported" })
  })

  it("reads a round's files, then sends those Import may send", () => {
    const round = asksOf(ROUND, LISTED, null)
    const answer = seenFile("XES 03-26.Last.txt", "imports")
    const files = (...states: FileState[]): ReviewedFile[] =>
      [MARCH, JUNE].map((upload, index) => ({ upload, state: states[index] }))
    const standing = (
      reviewed: readonly ReviewedFile[],
      request: ImportAsked | null = null,
      skipped: readonly string[] = []
    ) =>
      reviewStanding({
        asks: round,
        request,
        imported: false,
        review: unasked,
        files: reviewed,
        skipped,
      })

    expect(
      standing(
        files({ kind: "answered", answer }, { kind: "reading", last: null })
      )
    ).toEqual({ kind: "reading", again: false })
    expect(
      standing(
        files({ kind: "reading", last: answer }, { kind: "answered", answer })
      )
    ).toEqual({ kind: "reading", again: true })
    const refused: FileState = {
      kind: "answered",
      answer: seenFile("XES 06-26.Last.txt", "imported_before"),
    }
    expect(standing(files(refused, refused))).toEqual({
      kind: "nothing to send",
    })
    // D-105: a file that does not import waits for a decision, until it is skipped.
    const differs: FileState = {
      kind: "answered",
      answer: seenFile("XES 06-26.Last.txt", "differing"),
    }
    expect(standing(files({ kind: "answered", answer }, differs))).toEqual({
      kind: "to decide",
      files: 1,
    })
    expect(
      standing(files({ kind: "answered", answer }, differs), null, [JUNE.id])
    ).toEqual({ kind: "nothing to send" })
    const sent: ImportAsked = {
      kind: "files",
      sources: [
        { kind: "upload", upload_id: MARCH.id },
        { kind: "upload", upload_id: JUNE.id },
      ],
      profile: { kind: "named", name: "ninjatrader" },
      root: null,
      time_zone: null,
      differing: "refuse",
      leaving_out_bars_in_breaks: [],
    }
    expect(
      standing(
        files({ kind: "answered", answer }, { kind: "answered", answer }),
        sent
      )
    ).toEqual({ kind: "ready", files: 2 })
  })
})
