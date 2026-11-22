import { describe, expect, it } from "vitest"
import { parameterWords } from "./run-words"

describe("parameterWords", () => {
  it("names each parameter with its value, a nested one as its JSON", () => {
    expect(
      parameterWords({
        parameters: {
          lookback: 12,
          on: true,
          filter: { kind: "atr", length: 14 },
          levels: [1, 2],
          none: null,
        },
      })
    ).toBe(
      'lookback 12, on true, filter {"kind":"atr","length":14}, levels [1,2], none null'
    )
  })

  it("is empty for a run that names none", () => {
    expect(parameterWords({ parameters: {} })).toBe("")
  })
})
