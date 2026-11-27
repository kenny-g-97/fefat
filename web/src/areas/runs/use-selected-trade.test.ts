import { describe, expect, it } from "vitest"
import { firstOfNewPage, placeOf, shownTrade } from "./use-selected-trade"

const pages = (...rows: number[][]) => ({
  pages: rows.map((trades) => ({ trades })),
})

describe("the trade Next selects past the rows read", () => {
  it("is the first of the page the read added", () => {
    expect(
      firstOfNewPage({ isError: false, data: pages([1, 2], [3, 4]) }, 1)
    ).toBe(3)
  })

  it("is none where the read failed, which keeps the pages it held", () => {
    // Step 5.9's code review: TanStack Query answers a failed read of the next page with the
    // pages already read, whose last page's first trade stands before the selection.
    expect(
      firstOfNewPage({ isError: true, data: pages([1, 2]) }, 1)
    ).toBeUndefined()
    expect(
      firstOfNewPage({ isError: false, data: pages([1, 2]) }, 1)
    ).toBeUndefined()
    expect(
      firstOfNewPage({ isError: false, data: undefined }, 1)
    ).toBeUndefined()
  })
})

describe("the trade the chart shows while the table reads", () => {
  it("keeps the trade it found for the row while a new filter's rows come", () => {
    // Step 5.9's ponytail review: a new filter or order has no rows until its first page
    // comes, and the chart lost its trade meanwhile and drew the newest bars.
    const kept = { trade: 7 }

    expect(shownTrade(null, kept, 7)).toBe(kept)
    expect(shownTrade(null, kept, 8)).toBeNull()
    expect(shownTrade({ trade: 8 }, kept, 8)).toEqual({ trade: 8 })
    expect(shownTrade(null, null, 7)).toBeNull()
  })
})

describe("where the selected trade stands among the table's", () => {
  it("is its place where the table read it, further down where its filters keep it, and out where they hide it", () => {
    // Step 5.9's ponytail review: a reload past the rows read said the trade was not in the
    // table.
    expect(placeOf(2, 18, null)).toEqual({ kind: "at", at: 3, of: 18 })
    expect(placeOf(-1, 500, true)).toEqual({ kind: "further" })
    expect(placeOf(-1, 18, false)).toEqual({ kind: "hidden" })
    expect(placeOf(-1, 18, null)).toBeNull()
    expect(placeOf(2, null, null)).toBeNull()
  })
})
