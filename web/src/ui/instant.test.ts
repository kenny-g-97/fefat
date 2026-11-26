import { describe, expect, it } from "vitest"
import { formatInstant, formatInstantToTheSecond } from "./instant"

// vite.config.ts runs the tests in America/Chicago, six hours behind UTC in March.

describe("an instant in this browser's time zone", () => {
  it("reads to the minute, as every date and time of the app does", () => {
    expect(formatInstant("2026-03-05T14:35:07.495809902Z")).toBe(
      "2026-03-05 08:35"
    )
  })

  it("reads to the second in a table of trades, its fraction dropped", () => {
    expect(formatInstantToTheSecond("2026-03-05T14:35:07.995809902Z")).toBe(
      "2026-03-05 08:35:07"
    )
    expect(formatInstantToTheSecond("2026-03-06T00:00:00Z")).toBe(
      "2026-03-05 18:00:00"
    )
  })

  it("refuses text that is no instant", () => {
    expect(() => formatInstantToTheSecond("yesterday")).toThrow(
      'Expected an ISO 8601 instant, got "yesterday".'
    )
  })
})
