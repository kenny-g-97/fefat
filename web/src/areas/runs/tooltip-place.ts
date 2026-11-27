/** Where a fill's tooltip stands: its fill's point in the chart's first pane, and the size of the
 * chart it stands over. */
export type TooltipPlace = Readonly<{
  x: number
  y: number
  width: number
  height: number
}>

/** How far the tooltip stands from its fill's point: clear of the widest arrow the chart draws,
 * the selected trade's at Lightweight Charts' widest bar spacing, 61 px across. */
const GAP = 36
/** How near the chart's side edge the tooltip turns to the other side: its width with its gap. */
const ACROSS = 208
/** How near the chart's top or foot the tooltip stops following its point: half its height. */
const HALF = 36

/** The tooltip's place over the chart (web/DESIGN.md, Patterns, Marker tooltip): beside its fill
 * at its price, never over the fill's own arrow or the trade's bars: before the trade's first
 * fill, the entry, and after any other, turned the other way near the chart's side edges, and
 * kept inside the chart near its top and its foot. */
export function tooltipBox(
  place: TooltipPlace,
  first: boolean
): Readonly<{ left: number; top: number; transform: string }> {
  const before = first ? place.x >= ACROSS : place.x > place.width - ACROSS
  return {
    left: before ? place.x - GAP : place.x + GAP,
    top: Math.min(Math.max(place.y, HALF), place.height - HALF),
    transform: `translate(${before ? "-100%" : "0%"}, -50%)`,
  }
}
