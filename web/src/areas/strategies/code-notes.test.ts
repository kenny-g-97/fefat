import { describe, expect, it } from "vitest"
import type { LintFinding, StrategyVerdict } from "@/api/strategies"
import { codeLines, editorNotes, type Judged } from "./code-notes"

const SAVED = "def strategy(lookback: int = 12) -> ff.SignalStrategy: ...\n"
const EDITED = SAVED.replace("= 12", "= 24")
const READS_AHEAD: LintFinding = {
  rule: "negative_shift",
  line: 12,
  source: "close.rolling_max(lookback).shift(-1)",
  explanation: "A negative shift reads a later row's value.",
}
const saved = { code: SAVED, lint: [READS_AHEAD] }

describe("codeLines", () => {
  it("shows the saved version's own warnings while the code is its own", () => {
    expect(codeLines(SAVED, saved, null, null)).toEqual([
      { line: 12, severity: "warning", message: READS_AHEAD.explanation },
    ])
  })

  it("shows nothing for code no one has judged", () => {
    expect(codeLines(EDITED, saved, null, null)).toEqual([])
  })

  it("shows Validate's verdict on the code it judged, and none once the code changes", () => {
    const refused: Judged<StrategyVerdict> = {
      code: EDITED,
      answer: {
        verdict: "refused",
        line: 7,
        message: "SyntaxError: invalid syntax",
      },
    }

    expect([
      codeLines(EDITED, saved, refused, null),
      codeLines(EDITED.replace("24", "36"), saved, refused, null),
    ]).toEqual([
      [{ line: 7, severity: "error", message: "SyntaxError: invalid syntax" }],
      [],
    ])
  })

  it("shows a valid verdict's warnings, and a save's refusal over it", () => {
    const valid: Judged<StrategyVerdict> = {
      code: EDITED,
      answer: {
        verdict: "valid",
        instrument: "MES",
        timeframe: "5m",
        parameter_schema: {},
        lint: [READS_AHEAD],
      },
    }
    const refusal = {
      code: EDITED,
      answer: { line: null, message: "Expected the hypothesis on one line." },
    }

    expect([
      codeLines(EDITED, saved, valid, null),
      codeLines(EDITED, saved, valid, refusal),
    ]).toEqual([
      [{ line: 12, severity: "warning", message: READS_AHEAD.explanation }],
      [
        {
          line: null,
          severity: "error",
          message: "Expected the hypothesis on one line.",
        },
      ],
    ])
  })
})

describe("editorNotes", () => {
  it("underlines the lines at a line of the code alone", () => {
    expect(
      editorNotes([
        { line: 7, severity: "error", message: "SyntaxError" },
        { line: null, severity: "error", message: "Ran out of time" },
      ])
    ).toEqual([{ line: 7, severity: "error", message: "SyntaxError" }])
  })
})
