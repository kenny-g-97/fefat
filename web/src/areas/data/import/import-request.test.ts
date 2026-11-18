import { describe, expect, it } from "vitest"
import type { UploadedFile } from "@/api/imports"
import type { components } from "@/api/schema"
import { drafted, NEW_INSTRUMENT, startingDraft } from "./import-draft"
import {
  IBKR,
  LISTED,
  NINJATRADER,
  NINJATRADER_TABLE,
} from "./import-fixtures.test-support"
import { asksOf, offsetRefusal } from "./import-request"

const UPLOAD: UploadedFile = {
  id: "0193a000-0000-7000-8000-000000000001",
  name: "XES 03-26.Last.txt",
  size: 42,
  sha256: "0".repeat(64),
  uploaded_at: "2026-11-15T10:00:00Z",
}
const CHOSEN = drafted(startingDraft({ kind: "none" }), {
  kind: "source",
  source: { kind: "uploads", uploads: [UPLOAD] },
})
const SOURCE = { kind: "upload", upload_id: UPLOAD.id }

type OffsetSeen = components["schemas"]["OffsetSeen"]

describe("asksOf", () => {
  it("asks nothing before a file, and the table alone before a profile", () => {
    expect(asksOf(startingDraft({ kind: "none" }), LISTED, null)).toEqual({
      table: null,
      review: null,
      several: [],
      missing: [
        { card: "file", text: "Choose files, or type a path" },
        { card: "layout", text: "Choose a profile, or make one" },
      ],
    })
    expect(asksOf(CHOSEN, LISTED, null)).toEqual({
      table: { kind: "table", source: SOURCE },
      review: null,
      several: [],
      missing: [{ card: "layout", text: "Choose a profile, or make one" }],
    })
  })

  it("says what every card misses before a file, as each step of the wizard does (D-105)", () => {
    const zoneless = startingDraft({ kind: "profile", name: "ibkr" })
    const made = drafted(startingDraft({ kind: "none" }), {
      kind: "new profile",
      base: NINJATRADER,
    })
    const nameless = drafted(made, {
      kind: "profile fields",
      fields: { name: " " },
    })

    expect(asksOf(zoneless, LISTED, null).missing).toEqual([
      { card: "file", text: "Choose files, or type a path" },
      { card: "layout", text: "Type the time zone of the file's times" },
    ])
    expect(
      asksOf(
        startingDraft({ kind: "profile", name: "ninjatrader" }),
        LISTED,
        null
      ).missing
    ).toEqual([{ card: "file", text: "Choose files, or type a path" }])
    expect(asksOf(nameless, LISTED, null).missing).toEqual([
      { card: "file", text: "Choose files, or type a path" },
      { card: "layout", text: "Give the profile a name" },
    ])
    expect(asksOf(startingDraft({ kind: "batch" }), LISTED, null)).toEqual({
      table: null,
      review: null,
      several: [],
      missing: [{ card: "file", text: "Type the path of the batch's folder" }],
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
      bars_in_breaks: "refuse",
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

  it("asks a new profile's time zone, which no field of the import gives", () => {
    const zoneless = drafted(
      drafted(CHOSEN, { kind: "new profile", base: IBKR }),
      { kind: "profile fields", fields: { name: "my-ibkr" } }
    )

    expect(asksOf(zoneless, LISTED, NINJATRADER_TABLE).missing).toEqual([
      { card: "layout", text: "Type the time zone of the file's times" },
    ])
  })

  it("asks a column for each role once the base's columns no longer fit", () => {
    const made = drafted(CHOSEN, { kind: "new profile", base: NINJATRADER })
    const ticks = drafted(made, {
      kind: "profile fields",
      fields: { timeframe: "ticks", roles: { kind: "kept" } },
    })
    const named = drafted(made, {
      kind: "profile fields",
      fields: { header: true, roles: { kind: "kept" } },
    })

    expect(asksOf(ticks, LISTED, NINJATRADER_TABLE).missing).toEqual([
      { card: "layout", text: "Choose the column of the price" },
      { card: "layout", text: "Choose the column of the size" },
    ])
    expect(
      asksOf(named, LISTED, NINJATRADER_TABLE).missing.map((each) => each.text)
    ).toEqual([
      "Choose the column of the timestamp",
      "Choose the column of the open",
      "Choose the column of the high",
      "Choose the column of the low",
      "Choose the column of the close",
      "Choose the column of the volume",
    ])
  })

  it("asks a whole number of business days before the 25th", () => {
    const made = drafted(
      drafted(CHOSEN, { kind: "new profile", base: NINJATRADER }),
      {
        kind: "instrument",
        instrument: {
          kind: "new",
          fields: {
            ...NEW_INSTRUMENT,
            root: "XCL",
            tickSize: "0.01",
            pointValue: "1000",
            firstTradeDate: "2010-01-04",
            lastTradeRule: "business-days-before-the-25th",
            businessDays: "",
          },
        },
      }
    )
    const three = drafted(made, {
      kind: "instrument fields",
      fields: { businessDays: "3" },
    })

    expect(asksOf(made, LISTED, NINJATRADER_TABLE).missing).toEqual([
      {
        card: "instrument",
        text: "Give its business days before the 25th, a whole number from 1",
      },
    ])
    expect(asksOf(three, LISTED, NINJATRADER_TABLE).review).toMatchObject({
      profile: {
        profile: {
          instrument: {
            last_trade_rule: {
              kind: "business-days-before-the-25th",
              business_days: 3,
            },
          },
        },
      },
    })
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
      several: [],
      missing: [],
    })
  })

  it("asks a review of each of several files, each file's name giving its contract", () => {
    const june = {
      ...UPLOAD,
      id: "0193a000-0000-7000-8000-000000000002",
      name: "XES 06-26.Last.txt",
    }
    const several = drafted(
      drafted(
        drafted(CHOSEN, {
          kind: "source",
          source: { kind: "uploads", uploads: [UPLOAD, june] },
        }),
        { kind: "listed profile", name: "ninjatrader" }
      ),
      { kind: "contract", contract: "XESH2026" }
    )

    const asks = asksOf(several, LISTED, null)

    expect(asks.table).toEqual({
      kind: "table",
      source: SOURCE,
      layout: NINJATRADER.layout,
    })
    expect(asks.review).toBeNull()
    expect(asks.several).toEqual(
      [UPLOAD, june].map((each) => ({
        kind: "file",
        source: { kind: "upload", upload_id: each.id },
        contract: null,
        root: null,
        differing: "refuse",
        bars_in_breaks: "refuse",
        profile: { kind: "named", name: "ninjatrader" },
        time_zone: null,
      }))
    )
  })

  it("asks each file's own choice for its bars in a break, as the trader approved it", () => {
    const june = {
      ...UPLOAD,
      id: "0193a000-0000-7000-8000-000000000002",
      name: "XES 06-26.Last.txt",
    }
    const several = drafted(
      drafted(
        drafted(CHOSEN, {
          kind: "source",
          source: { kind: "uploads", uploads: [UPLOAD, june] },
        }),
        { kind: "listed profile", name: "ninjatrader" }
      ),
      { kind: "bars in breaks", files: [june.id] }
    )
    const alone = drafted(
      drafted(CHOSEN, { kind: "listed profile", name: "ninjatrader" }),
      { kind: "bars in breaks", files: [UPLOAD.id] }
    )

    expect(
      asksOf(several, LISTED, null).several.map((ask) => ask.bars_in_breaks)
    ).toEqual(["refuse", "leave-out"])
    expect(asksOf(alone, LISTED, null).review).toMatchObject({
      bars_in_breaks: "leave-out",
    })
  })
})

describe("offsetRefusal", () => {
  const late: Omit<OffsetSeen, "cause"> = {
    direction: "late",
    duration: "6 hours",
    first_trade_date: "2026-02-02",
    last_trade_date: "2026-02-06",
    description: "Records 6 hours late.",
  }

  it("stands under the field the offset's cause points at", () => {
    const zone: OffsetSeen[] = [{ ...late, cause: "time-zone" }]
    const either: OffsetSeen[] = [
      { ...late, cause: "time-zone-or-bar-stamping" },
    ]

    expect(offsetRefusal(zone, "time zone")).toBe(
      "The records run 6 hours late against their calendar"
    )
    expect(offsetRefusal(zone, "bar stamp")).toBeNull()
    expect(offsetRefusal(either, "bar stamp")).toBe(
      "The records run 6 hours late against their calendar"
    )
    expect(offsetRefusal([], "time zone")).toBeNull()
  })
})
