import { Text } from "@codemirror/state"
import { describe, expect, it } from "vitest"
import { lineSpan } from "./code-diagnostics"

const CODE = Text.of([
  "import polars as pl",
  "",
  "def strategy() -> ff.SignalStrategy:",
  '    close = pl.col("close") +',
])

describe("lineSpan", () => {
  it("underlines a line from its first character that is not a space", () => {
    const span = lineSpan(CODE, 4)

    expect(CODE.sliceString(span.from, span.to)).toBe(
      'close = pl.col("close") +'
    )
  })

  it("underlines the first line whole", () => {
    const span = lineSpan(CODE, 1)

    expect(CODE.sliceString(span.from, span.to)).toBe("import polars as pl")
  })

  it("puts an empty line's note at a point", () => {
    const span = lineSpan(CODE, 2)

    expect(span.from).toBe(span.to)
  })

  it("puts a note past the code's end on its last line", () => {
    expect(lineSpan(CODE, 9)).toEqual(lineSpan(CODE, 4))
  })

  it("refuses a line that is no line of code", () => {
    expect(() => lineSpan(CODE, 0)).toThrow(
      "Expected a line of the code from 1, got 0."
    )
  })
})
