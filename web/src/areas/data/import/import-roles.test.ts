import { describe, expect, it } from "vitest"
import { NINJATRADER } from "./import-fixtures.test-support"
import { mappingOf, rolesOf, withRole } from "./import-roles"

const SIX = [0, 1, 2, 3, 4, 5]

describe("rolesOf", () => {
  it("gives each column the role its profile maps it to", () => {
    expect(rolesOf(NINJATRADER.columns, [...SIX, 6])).toEqual([
      "timestamp",
      "open",
      "high",
      "low",
      "close",
      "volume",
      "unused",
    ])
  })
})

describe("withRole", () => {
  it("keeps one role a column and one column a role", () => {
    const roles = rolesOf(NINJATRADER.columns, SIX)

    expect(withRole(roles, 5, "open")).toEqual([
      "timestamp",
      "unused",
      "high",
      "low",
      "close",
      "open",
    ])
  })

  it("never keeps a timestamp beside a date and a time", () => {
    const dated = withRole(
      withRole(["timestamp", "unused"], 0, "date"),
      1,
      "time"
    )

    expect(dated).toEqual(["date", "time"])
    expect(withRole(dated, 1, "timestamp")).toEqual(["unused", "timestamp"])
  })
})

describe("mappingOf", () => {
  it("maps the roles back to the profile's columns", () => {
    const mapped = mappingOf(
      rolesOf(NINJATRADER.columns, SIX),
      SIX,
      false,
      NINJATRADER.columns
    )

    expect(mapped).toEqual({
      kind: "mapped",
      mapping: {
        timestamp: 0,
        date: null,
        time: null,
        symbol: null,
        instrument_id: null,
        record_type: null,
        bars: {
          open: 1,
          high: 2,
          low: 3,
          close: 4,
          volume: 5,
          trade_count: null,
          vwap: null,
        },
      },
    })
  })

  it("names what a bar or a tick still lacks", () => {
    expect(
      mappingOf(["date", "open", "unused"], ["d", "o", "x"], false, {})
    ).toEqual({
      kind: "missing",
      roles: ["timestamp", "high", "low", "close", "volume"],
    })
    expect(mappingOf(["timestamp", "price"], ["t", "p"], true, {})).toEqual({
      kind: "missing",
      roles: ["size"],
    })
  })
})
