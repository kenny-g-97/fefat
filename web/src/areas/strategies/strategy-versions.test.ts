import { describe, expect, it } from "vitest"
import { comparedVersion } from "./strategy-versions"

describe("comparedVersion", () => {
  it("sets the version before the one shown beside it, or the one after the first", () => {
    // Step 5.10: the Changes card compares the shown version with the one before it by default.
    expect(comparedVersion([1, 2, 3], 3, undefined)).toBe(2)
    expect(comparedVersion([1, 2, 3], 2, undefined)).toBe(1)
    expect(comparedVersion([1, 2, 3], 1, undefined)).toBe(2)
  })

  it("takes the version the address asks for where it is another of the strategy's", () => {
    expect(comparedVersion([1, 2, 3], 1, 3)).toBe(3)
    expect(comparedVersion([1, 2, 3], 2, 2)).toBe(1)
    expect(comparedVersion([1, 2, 3], 2, 7)).toBe(1)
  })

  it("sets none beside a strategy's only version", () => {
    expect(comparedVersion([1], 1, undefined)).toBeUndefined()
    expect(comparedVersion([1], 1, 1)).toBeUndefined()
  })
})
