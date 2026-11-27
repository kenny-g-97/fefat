import { counted, sentenceCase } from "@/ui/figures"
import { formatInstantToTheSecond } from "@/ui/instant"
import type { DrawnFill } from "./trade-panes"

/** Where the tooltip stands: its fill's point in the chart's first pane, and that pane's size. */
export type TooltipPlace = Readonly<{
  x: number
  y: number
  width: number
  height: number
}>

/** How far from the pane's edges the tooltip turns inward, and from its point it stands. */
const EDGE = 96
const GAP = 14

type MarkerTooltipProps = Readonly<{
  drawn: DrawnFill
  place: TooltipPlace
  pinned: boolean
}>

/** A fill's tooltip over the chart (web/DESIGN.md, Patterns, Marker tooltip): its role, side,
 * and lots, then its instant to the second as the trade table writes an entry, and its price as
 * the fills ledger holds it; above a buy's price, whose arrow stands under it, and under a
 * sell's, turned inward near the pane's edges. It is the selected trade's entry's while `pinned`,
 * and else the fill under the pointer or the keys' crosshair. */
export function MarkerTooltip({ drawn, place, pinned }: MarkerTooltipProps) {
  const { fill } = drawn
  const below =
    (fill.side === "sell" && place.y < place.height - EDGE) || place.y < EDGE
  const across =
    place.x < EDGE ? "0%" : place.x > place.width - EDGE ? "-100%" : "-50%"
  const up = below ? `${GAP}px` : `calc(-100% - ${GAP}px)`
  return (
    <div
      data-testid={pinned ? "entry-marker-tooltip" : "marker-tooltip"}
      className="pointer-events-none absolute z-10 flex flex-col gap-0.5 rounded-xl border bg-muted px-3 py-2 text-xs whitespace-nowrap shadow-md"
      style={{
        left: place.x,
        top: place.y,
        transform: `translate(${across}, ${up})`,
      }}
    >
      <span className="text-muted-foreground">
        {`${sentenceCase(fill.role)}, ${fill.side} ${counted(fill.lots, "lot")}`}
      </span>
      <span data-testid="marker-time" className="font-medium text-foreground">
        {formatInstantToTheSecond(fill.time)}
      </span>
      <span
        data-testid="marker-price"
        className="font-semibold text-foreground"
      >
        {fill.price}
      </span>
    </div>
  )
}
