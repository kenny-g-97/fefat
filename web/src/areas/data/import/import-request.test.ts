import { describe, expect, it } from "vitest"
import type { UploadedFile } from "@/api/imports"
import { drafted, NEW_INSTRUMENT, startingDraft } from "./import-draft"
import {
  LISTED,
  NINJATRADER,
  NINJATRADER_TABLE,
} from "./import-fixtures.test-support"
import { asksOf } from "./import-request"

const UPLOAD: UploadedFile = {
  id: "0193a000-0000-7000-8000-000000000001",
  name: "XES 03-26.Last.txt",
  size: 42,
  sha256: "0".repeat(64),
  uploaded_at: "2026-11-15T10:00:00Z",
}
const CHOSEN = drafted(startingDraft({ kind: "none" }), {
  kind: "source",
  source: { kind: "upload", upload: UPLOAD },
})
const SOURCE = { kind: "upload", upload_id: UPLOAD.id }

describe("asksOf", () => {
  it("asks nothing before a file, and the table alone before a profile", () => {
    expect(asksOf(startingDraft({ kind: "none" }), LISTED, null)).toEqual({
      table: null,
      review: null,
      missing: [{ card: "file", text: "Choose a file, or type its path" }],
    })
    expect(asksOf(CHOSEN, LISTED, null)).toEqual({
      table: { kind: "table", source: SOURCE },
      review: null,
      missing: [{ card: "layout", text: "Choose a profile, or make one" }],
    })
  })

  it("asks a listed profile by its name, with the time zone where it leaves it", () => {
    const named = drafted(CHOSEN, {
      kind: "listed profile",
      name: "ninjatrader",
    })
    const zoneless = drafted(CHOSEN, { kind: "listed profile", name: "ibkr" })

    expect(asksOf(named, LISTED, null).review).toEqual({
      kind: "file",
      source: SOURCE,
      contract: null,
      root: null,
      differing: "refuse",
      profile: { kind: "named", name: "ninjatrader" },
      time_zone: null,
    })
    expect(asksOf(zoneless, LISTED, null).missing).toEqual([
      { card: "layout", text: "Type the time zone of the file's times" },
    ])
    const zoned = drafted(zoneless, {
      kind: "time zone",
      timeZone: " America/New_York ",
    })
    expect(asksOf(zoned, LISTED, null).review).toMatchObject({
      time_zone: "America/New_York",
    })
  })

  it("gives a new profile whole, its description written from its fields", () => {
    const made = drafted(
      drafted(CHOSEN, { kind: "new profile", base: NINJATRADER }),
      {
        kind: "profile fields",
        fields: { name: "xes-minutes", timeZone: "America/Chicago" },
      }
    )

    const review = asksOf(made, LISTED, NINJATRADER_TABLE).review

    expect(review).toMatchObject({
      profile: {
        kind: "given",
        profile: {
          name: "xes-minutes",
          description:
            "ninjatrader 1m bars: semicolons, no header, America/Chicago, stamped at the close",
          timestamp: {
            format: "%Y%m%d %H%M%S",
            time_zone: "America/Chicago",
            stamp: "close",
          },
          columns: NINJATRADER.columns,
          contract_in_file_name: NINJATRADER.contract_in_file_name,
        },
      },
    })
  })

  it("says what a new instrument still lacks under the instrument's card", () => {
    const made = drafted(
      drafted(CHOSEN, { kind: "new profile", base: NINJATRADER }),
      {
        kind: "instrument",
        instrument: { kind: "new", fields: { ...NEW_INSTRUMENT, root: "XES" } },
      }
    )

    const asks = asksOf(made, LISTED, NINJATRADER_TABLE)

    expect(asks.review).toBeNull()
    expect(asks.missing.map((each) => each.card)).toEqual([
      "instrument",
      "instrument",
      "instrument",
    ])
  })

  it("asks a batch by its path", () => {
    const batch = drafted(startingDraft({ kind: "batch" }), {
      kind: "source",
      source: { kind: "path", path: "D:/batches/GLBX-1 " },
    })

    expect(asksOf(batch, LISTED, null)).toEqual({
      table: null,
      review: {
        kind: "databento",
        source: { kind: "path", path: "D:/batches/GLBX-1" },
        differing: "refuse",
      },
      missing: [],
    })
  })
})
