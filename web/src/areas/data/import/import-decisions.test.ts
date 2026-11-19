import { describe, expect, it } from "vitest"
import type { FileSeen, MergeSeen, UploadedFile } from "@/api/imports"
import {
  decisionWords,
  type RoundDecision,
  roundDecisions,
  skipAction,
} from "./import-decisions"
import { type Draft, startingDraft } from "./import-draft"
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
  decisions: Partial<Pick<Draft, "skipped" | "breaksLeftOut" | "differing">>
): Draft {
  return { ...startingDraft({ kind: "none" }), ...decisions }
}

function decision(
  problem: RoundDecision["problem"],
  files: number,
  skipped = 0,
  answer: RoundDecision["answer"] = null
): RoundDecision {
  const ids = Array.from({ length: files }, (_, index) => `f${index}`)
  return { problem, files: ids, skipped, answer }
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

    // A file whose records were taken stays in the box of records that differ.
    const differing = [
      read("c", "differing", MERGE),
      read("d", "imports", MERGE),
    ]
    const differingAnswer = (draft: Draft) =>
      roundDecisions(differing, draft).map((each) => each.answer)

    expect(differingAnswer(draftWith({}))).toEqual([null])
    expect(differingAnswer(draftWith({ differing: "take-file" }))).toEqual([
      "corrected",
    ])
    expect(
      differingAnswer(draftWith({ differing: "take-file", skipped: ["c"] }))
    ).toEqual(["corrected"])
    expect(
      differingAnswer(
        draftWith({ differing: "take-file", skipped: ["c", "d"] })
      )
    ).toEqual(["skipped"])
    expect(differingAnswer(draftWith({ skipped: ["c"] }))).toEqual([null])
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

describe("decisionWords", () => {
  it("words the box of bars in a break for several files and for one", () => {
    expect(decisionWords(decision("bars in breaks", 3))).toEqual({
      title: "3 files hold bars in a break",
      message:
        "These files hold bars at times when the market is closed, the last one closing at the next session's open: a sign that the platform stamped a stretch of bars early. Its own chart shows the same times, so check those sessions against another source if you can.",
      options: [
        {
          answer: "corrected",
          label: "Import them without those bars",
          description:
            "FEAT leaves out those bars and the sessions that go with them, and imports the rest of each file. Each file's row lists what goes.",
        },
        {
          answer: "skipped",
          label: "Skip them",
          description: "None of these 3 files is imported.",
        },
      ],
      notes: [],
    })
    expect(decisionWords(decision("bars in breaks", 1))).toEqual({
      title: "1 file holds bars in a break",
      message:
        "This file holds bars at times when the market is closed, the last one closing at the next session's open: a sign that the platform stamped a stretch of bars early. Its own chart shows the same times, so check those sessions against another source if you can.",
      options: [
        {
          answer: "corrected",
          label: "Import it without those bars",
          description:
            "FEAT leaves out those bars and the sessions that go with them, and imports the rest of the file. Its row lists what goes.",
        },
        {
          answer: "skipped",
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
          answer: "corrected",
          label: "Import them and replace the stored records",
          description:
            "The files' records take the place of the stored ones they differ from. Once imported, this cannot be undone.",
        },
        {
          answer: "skipped",
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
          answer: "corrected",
          label: "Import it and replace the stored records",
          description:
            "The file's records take the place of the stored ones they differ from. Once imported, this cannot be undone.",
        },
        {
          answer: "skipped",
          label: "Skip it",
          description: "The file is not imported, and the stored records stay.",
        },
      ],
      notes: [],
    })
  })

  it("words the box of the files no correction fits, which offers a skip alone", () => {
    expect(decisionWords(decision("not correctable", 2))).toEqual({
      title: "2 files do not import as they are read",
      message:
        "Each file's row says what stops it. Correct it under Layout or Instrument, which reads every file again, or skip these files.",
      options: [],
      notes: [],
    })
    expect(decisionWords(decision("not correctable", 1))).toEqual({
      title: "1 file does not import as it is read",
      message:
        "Its row says what stops it. Correct it under Layout or Instrument, which reads every file again, or skip the file.",
      options: [],
      notes: [],
    })
  })

  it("counts the files of a kind skipped where some are, and says what the calendar check lists once the bars are left out", () => {
    expect(decisionWords(decision("not correctable", 3, 1)).notes).toEqual([
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
})

describe("skipAction", () => {
  it("skips the files of the box not skipped yet, and once each is, takes the skip back", () => {
    expect(skipAction(decision("not correctable", 2))).toBe("Skip the 2 files")
    expect(skipAction(decision("not correctable", 2, 1))).toBe(
      "Skip the 1 file"
    )
    expect(skipAction(decision("not correctable", 2, 2, "skipped"))).toBe(
      "Do not skip them"
    )
    expect(skipAction(decision("not correctable", 1))).toBe("Skip the 1 file")
    expect(skipAction(decision("not correctable", 1, 1, "skipped"))).toBe(
      "Do not skip it"
    )
  })
})
