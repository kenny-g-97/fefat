import { describe, expect, it } from "vitest"
import type { FileSeen, MergeSeen, UploadedFile } from "@/api/imports"
import {
  allCorrected,
  decisionWords,
  type RoundDecision,
  roundDecisions,
  skipAction,
} from "./import-decisions"
import {
  type Answer,
  type Correctable,
  type Draft,
  startingDraft,
} from "./import-draft"
import { seenFile } from "./import-fixtures.test-support"
import type { FileState } from "./import-reviews"
import type { ReviewedFile } from "./import-round"

const BREAKS: NonNullable<FileSeen["breaks_with_bars"]> = {
  left_out: false,
  bars: 9,
  breaks: ["2026-02-03"],
  breaks_total: 1,
  sessions: ["2026-02-03", "2026-02-04"],
  sessions_total: 2,
  ending_a_bar_early: [],
  ending_a_bar_early_total: 0,
  records: 2_769,
}

const LEFT_OUT = { ...BREAKS, left_out: true }

const MERGE: MergeSeen = {
  dataset: { provider: "ninjatrader", schema_name: "ohlcv-1m", root: "ES" },
  new_sessions: 0,
  extended_sessions: 1,
  records_added: 0,
  records_held: 1_379,
  records_differing: 12,
  partitions_changed: 1,
  partitions_unchanged: 0,
  differing_sessions: ["2026-02-06"],
  differing_sessions_total: 1,
  stored_records_disputed: 12,
}

function upload(id: string): UploadedFile {
  return {
    id,
    name: `ES ${id}.Last.txt`,
    size: 42,
    sha256: "0".repeat(64),
    uploaded_at: "2026-11-19T10:00:00Z",
  }
}

function file(id: string, state: FileState): ReviewedFile {
  return { upload: upload(id), state }
}

/** A file of the round whose review came back with `verdict`. */
function read(
  id: string,
  verdict: FileSeen["verdict"],
  merge: FileSeen["merge"] = null,
  breaks: FileSeen["breaks_with_bars"] = null
): ReviewedFile {
  return file(id, {
    kind: "answered",
    answer: seenFile(`ES ${id}.Last.txt`, verdict, merge, breaks),
  })
}

function draftWith(
  decisions: Partial<Pick<Draft, "skipped" | "breaksLeftOut" | "recordsTaken">>
): Draft {
  return { ...startingDraft({ kind: "none" }), ...decisions }
}

function ids(files: number): string[] {
  return Array.from({ length: files }, (_, index) => `f${index}`)
}

/** A box a correction fits, of `files` files, `skipped` of them skipped. */
function decision(
  problem: Correctable,
  files: number,
  skipped = 0,
  answer: Answer | null = null
): RoundDecision {
  return { problem, files: ids(files), skipped, answer }
}

/** The box of `files` files no correction fits, `skipped` of them skipped. */
function notCorrectable(files: number, skipped = 0): RoundDecision {
  return {
    problem: "not correctable",
    files: ids(files),
    skipped,
    answer: skipped === files ? "skipped" : null,
  }
}

describe("roundDecisions", () => {
  it("asks of the kinds a round holds in order: bars in a break, records that differ, then the files no correction fits (D-106)", () => {
    const files = [
      read("a", "imports"),
      read("b", "refused"),
      read("c", "differing", MERGE),
      read("d", "bars_in_breaks", null, BREAKS),
      file("e", { kind: "failed", error: new Error("Gone.") }),
      read("f", "imported_before"),
      read("g", "nothing"),
    ]

    expect(roundDecisions(files, draftWith({}))).toEqual([
      { problem: "bars in breaks", files: ["d"], skipped: 0, answer: null },
      { problem: "differing", files: ["c"], skipped: 0, answer: null },
      {
        problem: "not correctable",
        files: ["b", "e"],
        skipped: 0,
        answer: null,
      },
    ])
    expect(roundDecisions([read("a", "imports")], draftWith({}))).toEqual([])
  })

  it("asks nothing until every file is read, a file read again counting by its last review", () => {
    const refused = seenFile("ES b.Last.txt", "refused")

    expect(
      roundDecisions(
        [read("a", "refused"), file("b", { kind: "reading", last: null })],
        draftWith({})
      )
    ).toEqual([])
    expect(
      roundDecisions(
        [read("a", "refused"), file("b", { kind: "reading", last: refused })],
        draftWith({})
      )
    ).toEqual([
      {
        problem: "not correctable",
        files: ["a", "b"],
        skipped: 0,
        answer: null,
      },
    ])
  })

  it("puts in the bars' box the files that leaving out their bars in a break lets in, or that it left out, by their last reviews while read again", () => {
    // A file refused for its bars alone, one read without them, and one still read again are in
    // it; one whose bars cannot be left out goes with the files no correction fits (ADR-0022).
    const files = [
      read("a", "bars_in_breaks", null, BREAKS),
      read("b", "imports", null, LEFT_OUT),
      read("c", "refused", null, BREAKS),
      read("d", "imports"),
      file("e", {
        kind: "reading",
        last: seenFile("ES e.Last.txt", "bars_in_breaks", null, BREAKS),
      }),
    ]

    expect(roundDecisions(files, draftWith({ breaksLeftOut: ["b"] }))).toEqual([
      {
        problem: "bars in breaks",
        files: ["a", "b", "e"],
        skipped: 0,
        answer: null,
      },
      { problem: "not correctable", files: ["c"], skipped: 0, answer: null },
    ])
  })

  it("puts a file its correction leaves refused in the box of the files no correction fits as well, so that its skip is offered (the code review)", () => {
    // Read without its bars, a file can still be refused, as one beside records that differ can.
    const files = [
      read("a", "refused", null, LEFT_OUT),
      read("b", "refused", MERGE),
    ]

    expect(roundDecisions(files, draftWith({ breaksLeftOut: ["a"] }))).toEqual([
      {
        problem: "bars in breaks",
        files: ["a"],
        skipped: 0,
        answer: "corrected",
      },
      { problem: "differing", files: ["b"], skipped: 0, answer: null },
      {
        problem: "not correctable",
        files: ["a", "b"],
        skipped: 0,
        answer: null,
      },
    ])
  })

  it("keeps a box's files once they are skipped, and counts them apart", () => {
    const files = [
      read("a", "bars_in_breaks", null, BREAKS),
      read("b", "bars_in_breaks", null, BREAKS),
      read("c", "refused"),
    ]

    expect(roundDecisions(files, draftWith({ skipped: ["b", "c"] }))).toEqual([
      {
        problem: "bars in breaks",
        files: ["a", "b"],
        skipped: 1,
        answer: null,
      },
      {
        problem: "not correctable",
        files: ["c"],
        skipped: 1,
        answer: "skipped",
      },
    ])
  })

  it("answers a box skipped where each of its files is, corrected where each of the others carries the correction, and none otherwise", () => {
    const bars = [
      read("a", "bars_in_breaks", null, BREAKS),
      read("b", "bars_in_breaks", null, BREAKS),
    ]
    const barsAnswer = (draft: Draft) =>
      roundDecisions(bars, draft).map((each) => each.answer)

    expect(barsAnswer(draftWith({}))).toEqual([null])
    expect(barsAnswer(draftWith({ breaksLeftOut: ["a"] }))).toEqual([null])
    expect(barsAnswer(draftWith({ breaksLeftOut: ["a", "b"] }))).toEqual([
      "corrected",
    ])
    expect(
      barsAnswer(draftWith({ breaksLeftOut: ["a"], skipped: ["b"] }))
    ).toEqual(["corrected"])
    expect(barsAnswer(draftWith({ skipped: ["a"] }))).toEqual([null])
    expect(
      barsAnswer(draftWith({ breaksLeftOut: ["a", "b"], skipped: ["b", "a"] }))
    ).toEqual(["skipped"])

    // A file whose records were taken stays in the box of records that differ, and the box is
    // answered for the files whose records the trader chose to take.
    const differing = [
      read("c", "differing", MERGE),
      read("d", "imports", MERGE),
    ]
    const differingAnswer = (draft: Draft) =>
      roundDecisions(differing, draft).map((each) => each.answer)

    expect(differingAnswer(draftWith({}))).toEqual([null])
    expect(differingAnswer(draftWith({ recordsTaken: ["c", "d"] }))).toEqual([
      "corrected",
    ])
    expect(differingAnswer(draftWith({ recordsTaken: ["d"] }))).toEqual([null])
    expect(
      differingAnswer(draftWith({ recordsTaken: ["d"], skipped: ["c"] }))
    ).toEqual(["corrected"])
    expect(differingAnswer(draftWith({ skipped: ["c", "d"] }))).toEqual([
      "skipped",
    ])
    expect(differingAnswer(draftWith({ skipped: ["c"] }))).toEqual([null])
  })

  it("leaves a file that comes to differ once its bars are left out unanswered, though the box's other files were answered (the ponytail review)", () => {
    const files = [
      read("d", "imports", MERGE),
      read("y", "differing", MERGE, LEFT_OUT),
    ]

    expect(
      roundDecisions(
        files,
        draftWith({ breaksLeftOut: ["y"], recordsTaken: ["d"] })
      )
    ).toEqual([
      {
        problem: "bars in breaks",
        files: ["y"],
        skipped: 0,
        answer: "corrected",
      },
      { problem: "differing", files: ["d", "y"], skipped: 0, answer: null },
    ])
  })

  it("counts a file read without its bars in a break that then differs in both boxes", () => {
    const files = [read("a", "differing", MERGE, LEFT_OUT)]

    expect(roundDecisions(files, draftWith({ breaksLeftOut: ["a"] }))).toEqual([
      {
        problem: "bars in breaks",
        files: ["a"],
        skipped: 0,
        answer: "corrected",
      },
      { problem: "differing", files: ["a"], skipped: 0, answer: null },
    ])
  })
})

describe("allCorrected", () => {
  it("holds where each of one or more files carries the correction, and never for no file", () => {
    expect(allCorrected(["a"], ["a", "b"])).toBe(true)
    expect(allCorrected(["a", "c"], ["a", "b"])).toBe(false)
    expect(allCorrected([], ["a"])).toBe(false)
  })
})

describe("decisionWords", () => {
  it("words the box of bars in a break for several files and for one", () => {
    expect(decisionWords(decision("bars in breaks", 3))).toEqual({
      title: "3 files hold bars in a break",
      message:
        "These files hold bars at times when the market is closed, the last one closing at the next session's open: a sign that the platform stamped a stretch of bars early. Its own chart shows the same times, so check the sessions each file's row lists against another source if you can.",
      options: [
        {
          value: "corrected",
          label: "Import them without those bars",
          description:
            "FEAT leaves out those bars and the sessions that go with them, and imports the rest of each file. Each file's row lists what goes.",
        },
        {
          value: "skipped",
          label: "Skip them",
          description: "None of these 3 files is imported.",
        },
      ],
      notes: [],
    })
    expect(decisionWords(decision("bars in breaks", 1))).toEqual({
      title: "1 file holds bars in a break",
      message:
        "This file holds bars at times when the market is closed, the last one closing at the next session's open: a sign that the platform stamped a stretch of bars early. Its own chart shows the same times, so check the sessions its row lists against another source if you can.",
      options: [
        {
          value: "corrected",
          label: "Import it without those bars",
          description:
            "FEAT leaves out those bars and the sessions that go with them, and imports the rest of the file. Its row lists what goes.",
        },
        {
          value: "skipped",
          label: "Skip it",
          description: "The file is not imported.",
        },
      ],
      notes: [],
    })
  })

  it("words the box of records that differ for several files and for one", () => {
    expect(decisionWords(decision("differing", 2))).toEqual({
      title: "2 files hold records that differ from the ones FEAT holds",
      message:
        "Where the files are exports, check their profile's time zone and bar stamping under Layout first. Where they hold a vendor's correction, their records should replace the stored ones.",
      options: [
        {
          value: "corrected",
          label: "Import them and replace the stored records",
          description:
            "The files' records take the place of the stored ones they differ from. Once imported, this cannot be undone.",
        },
        {
          value: "skipped",
          label: "Skip them",
          description:
            "None of these 2 files is imported, and the stored records stay.",
        },
      ],
      notes: [],
    })
    expect(decisionWords(decision("differing", 1))).toEqual({
      title: "1 file holds records that differ from the ones FEAT holds",
      message:
        "Where the file is an export, check its profile's time zone and bar stamping under Layout first. Where it holds a vendor's correction, its records should replace the stored ones.",
      options: [
        {
          value: "corrected",
          label: "Import it and replace the stored records",
          description:
            "The file's records take the place of the stored ones they differ from. Once imported, this cannot be undone.",
        },
        {
          value: "skipped",
          label: "Skip it",
          description: "The file is not imported, and the stored records stay.",
        },
      ],
      notes: [],
    })
  })

  it("words the box of the files no correction fits, which offers a skip alone", () => {
    expect(decisionWords(notCorrectable(2))).toEqual({
      title: "2 files do not import as they are read",
      message:
        "Each file's row says what stops it. Correct it under Layout or Instrument, which reads every file again, or skip these files.",
      options: [],
      notes: [],
    })
    expect(decisionWords(notCorrectable(1))).toEqual({
      title: "1 file does not import as it is read",
      message:
        "Its row says what stops it. Correct it under Layout or Instrument, which reads every file again, or skip the file.",
      options: [],
      notes: [],
    })
  })

  it("counts the files of a kind skipped where some are, and says what the calendar check lists once the bars are left out", () => {
    expect(decisionWords(notCorrectable(3, 1)).notes).toEqual([
      "1 of these 3 files is skipped.",
    ])
    expect(decisionWords(decision("differing", 3, 2)).notes).toEqual([
      "2 of these 3 files are skipped.",
    ])
    expect(decisionWords(decision("differing", 3, 3, "skipped")).notes).toEqual(
      []
    )
    expect(
      decisionWords(decision("bars in breaks", 3, 1, "corrected")).notes
    ).toEqual([
      "1 of these 3 files is skipped.",
      "Each file's calendar check may list the sessions left out as having no prints.",
    ])
    expect(
      decisionWords(decision("bars in breaks", 1, 0, "corrected")).notes
    ).toEqual([
      "The file's calendar check may list the sessions left out as having no prints.",
    ])
  })

  it("says that the files no correction fits are skipped once each is, since their box has no option to show it (the design review)", () => {
    expect(decisionWords(notCorrectable(3, 3)).notes).toEqual([
      "These 3 files are skipped.",
    ])
    expect(decisionWords(notCorrectable(1, 1)).notes).toEqual([
      "The file is skipped.",
    ])
  })
})

describe("skipAction", () => {
  it("skips the files of the box not skipped yet, the others where some are, and once each is, takes the skip back", () => {
    expect(skipAction(notCorrectable(2))).toBe("Skip the 2 files")
    expect(skipAction(notCorrectable(2, 1))).toBe("Skip the other file")
    expect(skipAction(notCorrectable(3, 1))).toBe("Skip the other 2 files")
    expect(skipAction(notCorrectable(2, 2))).toBe("Do not skip them")
    expect(skipAction(notCorrectable(1))).toBe("Skip the file")
    expect(skipAction(notCorrectable(1, 1))).toBe("Do not skip it")
  })
})
