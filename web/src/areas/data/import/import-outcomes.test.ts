import { describe, expect, it } from "vitest"
import type { FileSeen, MergeSeen } from "@/api/imports"
import { seenFile } from "./import-fixtures.test-support"
import { OUTCOME_SIGNS, roundLine, whyNot } from "./import-outcomes"
import type { FileState } from "./import-reviews"

const NAME = "XES 03-26.Last.txt"

function answered(seen: FileSeen): FileState {
  return { kind: "answered", answer: seen }
}

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

const MERGE: MergeSeen = {
  dataset: { provider: "ninjatrader", schema_name: "ohlcv-1m", root: "XES" },
  new_sessions: 0,
  extended_sessions: 1,
  records_added: 0,
  records_held: 1_379,
  records_differing: 1,
  partitions_changed: 1,
  partitions_unchanged: 0,
  differing_sessions: ["2026-02-06"],
  differing_sessions_total: 1,
  stored_records_disputed: 1,
}

describe("whyNot", () => {
  it("says nothing of a file that imports, was imported before, holds nothing, or is still read", () => {
    for (const verdict of ["imports", "imported_before", "nothing"] as const) {
      expect(whyNot(answered(seenFile(NAME, verdict)), "UTC")).toBeNull()
    }
    expect(whyNot({ kind: "reading", last: null }, "UTC")).toBeNull()
  })

  it("gives a refused file's first offset with what to check, else its first problem", () => {
    const late: FileSeen = {
      ...seenFile(NAME, "refused"),
      offsets: [
        {
          cause: "time-zone",
          direction: "late",
          duration: "6 hours",
          first_trade_date: "2026-02-02",
          last_trade_date: "2026-02-06",
          description: "Records 6 hours late.",
        },
      ],
      problems: ["Expected a price, got 'x' on row 3."],
      problems_total: 1,
    }
    const problem: FileSeen = { ...late, offsets: [] }

    expect(whyNot(answered(late), "America/Chicago")).toBe(
      "The records run 6 hours late against their calendar on the trade dates 2026-02-02 to 2026-02-06: check the time zone of the file's times, America/Chicago."
    )
    expect(whyNot(answered(problem), "UTC")).toBe(
      "Expected a price, got 'x' on row 3."
    )
    expect(whyNot(answered({ ...problem, problems: [] }), "UTC")).toBe(
      "It would be refused"
    )
  })

  it("counts the bars in a break and the records that differ that stop a file", () => {
    expect(
      whyNot(answered(seenFile(NAME, "bars_in_breaks", null, BREAKS)), "UTC")
    ).toBe(
      "It would be refused for its bars in a break: 9 bars in the break after the trade date 2026-02-03"
    )
    expect(whyNot(answered(seenFile(NAME, "differing", MERGE)), "UTC")).toBe(
      "Its records differ from the ones FEAT holds: 1 record on 2026-02-06"
    )
  })

  it("says why a file was not read", () => {
    expect(
      whyNot({ kind: "failed", error: new Error("The server is gone.") }, null)
    ).toBe("The server is gone.")
    const refused: FileState = {
      kind: "answered",
      answer: { kind: "refused", message: "Expected a table, got none." },
    }
    expect(whyNot(refused, null)).toBe("Expected a table, got none.")
  })
})

describe("OUTCOME_SIGNS", () => {
  it("marks a file that imports positive, one something stops negative, and one imported before or empty neither", () => {
    expect(OUTCOME_SIGNS).toEqual({
      imports: "positive",
      imports_without_bars: "positive",
      refused: "negative",
      bars_in_breaks: "negative",
      differing: "negative",
      unread: "negative",
      imported_before: "none",
      nothing: "none",
    })
  })
})

describe("roundLine", () => {
  it("counts a round's files skipped apart from those its reviews kept out (D-105)", () => {
    const round = {
      files_imported: 2,
      files_imported_before: 0,
      not_imported: [],
    }

    expect(roundLine(round, 3, 1, 0)).toBe(
      "2 of 3 files imported, 1 skipped, as you chose."
    )
    expect(roundLine(round, 4, 1, 1)).toBe(
      "2 of 4 files imported, 1 skipped, as you chose, 1 not sent, as its review said."
    )
    expect(roundLine({ ...round, files_imported_before: 1 }, 5, 0, 2)).toBe(
      "2 of 5 files imported, 1 file imported before, 2 not sent, as their reviews said."
    )
  })
})
