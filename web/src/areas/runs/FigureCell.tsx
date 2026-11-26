import { cn } from "cn"
import { TableCell } from "@/ui/table"
import type { Written } from "./side-figures"

/** The colour of each look of a figure (side-figures.ts). */
const LOOKS: Readonly<Record<Written["look"], string>> = {
  positive: "text-positive",
  negative: "text-negative",
  figure: "text-foreground",
  none: "text-foreground-secondary",
}

/** A figure of a table of a run's figures, By side's and buy and hold's: right-aligned in its
 * look's colour, the last column's padded to the card's edge. */
export function FigureCell({
  written,
  last,
}: Readonly<{ written: Written; last: boolean }>) {
  return (
    <TableCell
      className={cn(
        "py-0 text-right",
        last ? "pr-6 pl-3" : "px-3",
        LOOKS[written.look]
      )}
    >
      {written.text}
    </TableCell>
  )
}
