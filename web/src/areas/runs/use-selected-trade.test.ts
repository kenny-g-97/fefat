import { describe, expect, it } from "vitest"
import { firstOfNewPage } from "./use-selected-trade"

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
