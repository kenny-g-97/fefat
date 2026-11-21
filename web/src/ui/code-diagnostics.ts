import type { Text } from "@codemirror/state"

/** The span of `doc` a note at `line` underlines: the line's text from its first character that
 * is not a space, so that an indented line's underline starts under its code. A line past the
 * code's end is its last line: Python puts an error found at the end of the file, such as a
 * function without a body, on the line after it, where the code holds no final line break. */
export function lineSpan(
  doc: Text,
  line: number
): Readonly<{ from: number; to: number }> {
  if (!Number.isInteger(line) || line < 1) {
    throw new Error(`Expected a line of the code from 1, got ${line}.`)
  }
  const shown = doc.line(Math.min(line, doc.lines))
  const indent = shown.text.length - shown.text.trimStart().length
  return { from: shown.from + indent, to: shown.to }
}
