import { describe, expect, it } from "vitest"
import { compareSearch } from "./run-search"

const KEYS = ["a", "b", "c", "d", "e"].map((digit) => digit.repeat(64))

describe("compareSearch", () => {
  it("reads two to four run keys joined by commas, the first the reference", () => {
    // Step 5.10: the comparison's page is addressed by its runs' keys.
    expect(compareSearch.parse({ runs: KEYS.slice(0, 2).join(",") })).toEqual({
      runs: KEYS.slice(0, 2).join(","),
    })
    expect(compareSearch.parse({ runs: KEYS.slice(0, 4).join(",") }).runs).toBe(
      KEYS.slice(0, 4).join(",")
    )
  })

  it("leaves out an address of one run, five runs, or anything but run keys", () => {
    expect(compareSearch.parse({ runs: KEYS[0] }).runs).toBeUndefined()
    expect(compareSearch.parse({ runs: KEYS.join(",") }).runs).toBeUndefined()
    expect(
      compareSearch.parse({ runs: `${KEYS[0]},${KEYS[1].toUpperCase()}` }).runs
    ).toBeUndefined()
    expect(compareSearch.parse({}).runs).toBeUndefined()
  })
})
