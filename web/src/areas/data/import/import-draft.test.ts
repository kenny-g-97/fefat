import { describe, expect, it } from "vitest"
import { drafted, NEW_INSTRUMENT, startingDraft } from "./import-draft"
import { IBKR, NINJATRADER } from "./import-fixtures.test-support"

describe("drafted", () => {
  it("refuses differing records again at every change but the choice itself", () => {
    const taking = drafted(startingDraft({ kind: "none" }), {
      kind: "differing",
      differing: "take-file",
    })

    expect(taking.differing).toBe("take-file")
    expect(
      drafted(taking, { kind: "time zone", timeZone: "UTC" }).differing
    ).toBe("refuse")
  })

  it("leaves out the bars in a break of the files approved until another change", () => {
    const taking = drafted(startingDraft({ kind: "none" }), {
      kind: "differing",
      differing: "take-file",
    })

    const leaving = drafted(taking, { kind: "bars in breaks", files: ["a"] })

    expect(leaving.breaksLeftOut).toEqual(["a"])
    expect(leaving.differing).toBe("refuse")
    const taken = drafted(leaving, {
      kind: "differing",
      differing: "take-file",
    })
    expect(taken.breaksLeftOut).toEqual(["a"])
    expect(
      drafted(taken, { kind: "time zone", timeZone: "UTC" }).breaksLeftOut
    ).toEqual([])
  })

  it("keeps the files skipped through the three decisions, and skips none once what is read changes (D-105)", () => {
    const skipping = drafted(startingDraft({ kind: "none" }), {
      kind: "skipped",
      files: ["b"],
    })

    expect(skipping.skipped).toEqual(["b"])
    const taken = drafted(skipping, {
      kind: "differing",
      differing: "take-file",
    })
    expect(taken.skipped).toEqual(["b"])
    expect(taken.differing).toBe("take-file")
    expect(
      drafted(taken, { kind: "skipped", files: ["b", "c"] }).differing
    ).toBe("take-file")
    const leaving = drafted(taken, { kind: "bars in breaks", files: ["a"] })
    expect(leaving.skipped).toEqual(["b"])
    const again = drafted(leaving, { kind: "skipped", files: ["b", "c"] })
    expect(again.breaksLeftOut).toEqual(["a"])
    expect(again.skipped).toEqual(["b", "c"])
    expect(
      drafted(again, { kind: "time zone", timeZone: "UTC" }).skipped
    ).toEqual([])
    expect(
      drafted(again, { kind: "source", source: { kind: "none" } }).skipped
    ).toEqual([])
  })

  it("copies a new profile from its base under a name of the trader's own", () => {
    const draft = drafted(
      startingDraft({ kind: "profile", name: "ninjatrader" }),
      {
        kind: "new profile",
        base: NINJATRADER,
      }
    )

    expect(draft.profile).toEqual({
      kind: "new",
      base: "ninjatrader",
      fields: {
        name: "my-ninjatrader",
        provider: "ninjatrader",
        delimiter: ";",
        header: false,
        format: "%Y%m%d %H%M%S",
        timeZone: "UTC",
        stamp: "close",
        timeframe: "1m",
        roles: { kind: "kept" },
      },
    })
    const zoned = drafted(draft, {
      kind: "profile fields",
      fields: { timeZone: "America/Chicago" },
    })
    expect(zoned.profile.kind === "new" && zoned.profile.fields.timeZone).toBe(
      "America/Chicago"
    )
  })

  it("gives a new profile made from a preset without a time zone the one typed for it", () => {
    const typed = drafted(startingDraft({ kind: "profile", name: "ibkr" }), {
      kind: "time zone",
      timeZone: "America/New_York",
    })

    const draft = drafted(typed, { kind: "new profile", base: IBKR })

    expect(draft.profile.kind === "new" && draft.profile.fields.timeZone).toBe(
      "America/New_York"
    )
  })

  it("copies a profile whose delimiter is any other single character", () => {
    const colons = { ...NINJATRADER, layout: { delimiter: ":", header: false } }

    const draft = drafted(startingDraft({ kind: "none" }), {
      kind: "new profile",
      base: colons,
    })

    expect(draft.profile.kind === "new" && draft.profile.fields.delimiter).toBe(
      ":"
    )
  })

  it("starts each preset's draft, and a batch's reading anew", () => {
    expect(startingDraft({ kind: "batch" }).reading).toBe("batch")
    const chosen = drafted(startingDraft({ kind: "none" }), {
      kind: "source",
      source: { kind: "path", path: "D:/exports/a.csv" },
    })
    expect(
      drafted(chosen, { kind: "reading", reading: "batch" }).source
    ).toEqual({
      kind: "none",
    })
  })

  it("refuses an edit of a profile or an instrument that is not new", () => {
    const listed = startingDraft({ kind: "profile", name: "ninjatrader" })

    expect(() =>
      drafted(listed, { kind: "profile fields", fields: { name: "x" } })
    ).toThrow("Expected a new profile to edit")
    expect(() =>
      drafted(listed, { kind: "instrument fields", fields: { root: "X" } })
    ).toThrow()
    const made = drafted(listed, {
      kind: "instrument",
      instrument: { kind: "new", fields: NEW_INSTRUMENT },
    })
    expect(
      drafted(made, { kind: "instrument fields", fields: { root: "XES" } })
        .instrument
    ).toEqual({ kind: "new", fields: { ...NEW_INSTRUMENT, root: "XES" } })
  })
})
