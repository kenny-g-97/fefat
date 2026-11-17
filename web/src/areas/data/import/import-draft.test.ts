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
