import { useVirtualizer } from "@tanstack/react-virtual"
import { type CSSProperties, type RefObject, useEffect, useState } from "react"

/** The height of a row of a data grid, and of its header row, which stays at the top of its box
 * (web/DESIGN.md, Patterns, Data grid): a table's 40 px. */
export const ROW_HEIGHT = 40

/** The least height of a data grid whose rows are taller, so that a short window still shows
 * some of them (web/DESIGN.md, Patterns, Trades page). */
const LEAST_HEIGHT = "10rem"

/** Rows drawn beyond either edge of the box, so that a quick scroll shows rows rather than
 * space. */
const OVERSCAN = 10

/** The rows of a data grid of `count` rows that `box` scrolls through, drawn only near its view
 * (TanStack Virtual): the rows to draw, and the room the rows not drawn take above and below
 * them, which a spacer row holds, so that the table keeps the columns of a real table; the
 * header row is the box's first 40 px, and a row the keys reach is scrolled to just under it. */
export function useVirtualRows(
  count: number,
  box: RefObject<HTMLDivElement | null>
) {
  // No React Compiler memoizes this app, which the rule guards against.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => box.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: OVERSCAN,
    paddingStart: ROW_HEIGHT,
    scrollPaddingStart: ROW_HEIGHT,
  })
  const rows = virtualizer.getVirtualItems()
  const first = rows.at(0)
  const last = rows.at(-1)
  return {
    virtualizer,
    rows,
    above: first === undefined ? 0 : first.start - ROW_HEIGHT,
    below: last === undefined ? 0 : virtualizer.getTotalSize() - last.end,
  }
}

/** The heights of a data grid of `count` rows: as tall as its rows and its header up to what the
 * page leaves, and never under `LEAST_HEIGHT` where its rows are taller, so that a short answer
 * leaves no empty band under its rows; the least alone while the count is not known. */
export function gridHeights(count: number | null): CSSProperties {
  if (count === null) {
    return { minHeight: LEAST_HEIGHT }
  }
  const rows = `${(count + 1) * ROW_HEIGHT + 2}px`
  return { maxHeight: rows, minHeight: `min(${LEAST_HEIGHT}, ${rows})` }
}

/** Whether `box` is scrolled sideways, which the frozen first column marks with a hairline at its
 * edge, so that nothing passes under it unseen (web/DESIGN.md, Patterns, Data grid). */
export function useScrolledSideways(
  box: RefObject<HTMLDivElement | null>
): boolean {
  const [sideways, setSideways] = useState(false)
  useEffect(() => {
    const element = box.current
    if (element === null) {
      return
    }
    const follow = () => setSideways(element.scrollLeft > 0)
    element.addEventListener("scroll", follow, { passive: true })
    return () => element.removeEventListener("scroll", follow)
  }, [box])
  return sideways
}
