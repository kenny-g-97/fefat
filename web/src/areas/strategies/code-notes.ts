import type { LintFinding, StrategyVerdict } from "@/api/strategies"
import type { CodeNote } from "@/ui/code-editor"

/** A refusal of the code or a warning on it, at its line, which a refusal may lack. */
export type CodeLine = Readonly<{
  line: number | null
  severity: "error" | "warning"
  message: string
}>

/** What the server said of code, with the code it was given: Validate's verdict, or a save's
 * refusal. */
export type Judged<Answer> = Readonly<{ code: string; answer: Answer }>

/** A save the SDK refused, with the line of the code it is at, if any. */
export type SaveRefusal = Readonly<{ line: number | null; message: string }>

/** What stands under the editor for `code`: the last save's refusal or Validate's verdict where
 * either judged this very code, the page asking one at a time, else the warnings the saved
 * version carries while the code is its own; nothing for code no one has judged. The browser
 * judges nothing itself: every line comes from the server's executor (Done means 4). */
export function codeLines(
  code: string,
  saved: Readonly<{ code: string; lint: readonly LintFinding[] }>,
  verdict: Judged<StrategyVerdict> | null,
  refusal: Judged<SaveRefusal> | null
): readonly CodeLine[] {
  if (refusal !== null && refusal.code === code) {
    return [{ ...refusal.answer, severity: "error" }]
  }
  if (verdict !== null && verdict.code === code) {
    const answer = verdict.answer
    return answer.verdict === "refused"
      ? [{ line: answer.line, severity: "error", message: answer.message }]
      : warnings(answer.lint)
  }
  return code === saved.code ? warnings(saved.lint) : []
}

/** The lines of `lines` the editor underlines, those at a line of the code. */
export function editorNotes(lines: readonly CodeLine[]): readonly CodeNote[] {
  return lines.flatMap((each) =>
    each.line === null
      ? []
      : [{ line: each.line, severity: each.severity, message: each.message }]
  )
}

function warnings(lint: readonly LintFinding[]): readonly CodeLine[] {
  return lint.map((finding) => ({
    line: finding.line,
    severity: "warning",
    message: finding.explanation,
  }))
}
