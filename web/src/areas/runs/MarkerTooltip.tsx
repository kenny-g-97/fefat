import { counted, sentenceCase } from "@/ui/figures"
import { formatInstantToTheSecond } from "@/ui/instant"
import { tooltipBox, type TooltipPlace } from "./tooltip-place"
import { type DrawnFill, fillId } from "./trade-panes"

type MarkerTooltipProps = Readonly<{
  drawn: DrawnFill
  place: TooltipPlace
  pinned: boolean
}>

/** A fill's tooltip over the chart (web/DESIGN.md, Patterns, Marker tooltip): its role, side,
 * and lots, then its instant to the second as the trade table writes an entry, and its price as
 * the fills ledger holds it, beside the fill (`tooltipBox`). It is the selected trade's entry's
 * while `pinned`, and else the fill under the pointer or the keys' crosshair. */
export function MarkerTooltip({ drawn, place, pinned }: MarkerTooltipProps) {
  const { fill } = drawn
  const box = tooltipBox(place, drawn.id === fillId(drawn.trade, 0))
  return (
    <div
      data-testid={pinned ? "entry-marker-tooltip" : "marker-tooltip"}
      className="pointer-events-none absolute z-10 flex flex-col gap-0.5 rounded-xl border bg-muted px-3 py-2 text-xs whitespace-nowrap shadow-md"
      style={box}
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
