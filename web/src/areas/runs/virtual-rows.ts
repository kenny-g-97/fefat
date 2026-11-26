import { useVirtualizer } from "@tanstack/react-virtual"
import type { RefObject } from "react"

/** The height of a row of a data grid, and of its header row, which stays at the top of its box
 * (web/DESIGN.md, Patterns, Data grid): a table's 40 px. */
export const ROW_HEIGHT = 40

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
