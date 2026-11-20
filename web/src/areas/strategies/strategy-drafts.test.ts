import { describe, expect, it } from "vitest"
import { draftKey, storedDraft } from "./strategy-drafts"

describe("storedDraft", () => {
  it("reads a draft kept as the page keeps one", () => {
    const draft = {
      code: "def strategy(lookback: int = 24) -> ff.SignalStrategy: ...\n",
      hypothesis: "A close above the highest of the hour runs on.",
      changelog: "A longer lookback.",
    }

    expect(storedDraft(JSON.stringify(draft))).toEqual(draft)
  })

  it("reads nothing kept, or what is no draft, as no draft", () => {
    expect(
      [null, "", "not json", JSON.stringify({ code: 12 }), "[]"].map(
        storedDraft
      )
    ).toEqual([null, null, null, null, null])
  })
})

describe("draftKey", () => {
  it("addresses a draft by its strategy's name and version", () => {
    expect(draftKey("breakout", 2)).toBe("fefat_strategy_draft:breakout:2")
  })
})
