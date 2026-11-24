import { cn } from "cn"
import type { ReactNode } from "react"
import { NO_BREAK_SPACE } from "@/ui/figures"

type StatProps = Readonly<{
  label: string
  value: ReactNode
  unit?: string | null
  detail?: ReactNode
  tone?: "positive" | "negative"
  inset?: boolean
  testId: string
}>

/** A stat card (web/DESIGN.md, Patterns, Stat card), one of a `dl`: its figure at 24 px in bold,
 * in the colour of its sign where it is money, with the `unit` after it at 12 px where one is
 * given, such as the code of a currency without a sign, its label under it, and one line of what
 * the figure is out of. The label comes first in the document, so that a screen reader names the
 * figure before reading it. An `inset` stat stands inside a card, on the control surface without
 * a shadow, as the boxes inside cards do, and spans three rows of its `dl`'s grid, so that the
 * stats of a row keep their figures, labels, and lines in line where a label takes two lines. */
export function Stat({
  label,
  value,
  unit,
  detail,
  tone,
  inset = false,
  testId,
}: StatProps) {
  return (
    <div
      data-testid={testId}
      className={cn(
        "rounded-xl border p-5",
        inset
          ? "row-span-3 grid grid-rows-subgrid gap-0 bg-muted"
          : "flex flex-col bg-card shadow-raised"
      )}
    >
      <dt className="order-2 mt-1 text-foreground-secondary">{label}</dt>
      <dd
        className={cn(
          "order-1 text-2xl font-bold tracking-tight text-foreground",
          tone === "positive" && "text-positive",
          tone === "negative" && "text-negative"
        )}
      >
        {value}
        {typeof unit === "string" && (
          <>
            {NO_BREAK_SPACE}
            <span className="text-xs font-semibold tracking-normal">
              {unit}
            </span>
          </>
        )}
      </dd>
      {detail !== undefined && (
        <dd className="order-3 mt-1 text-xs text-muted-foreground">{detail}</dd>
      )}
    </div>
  )
}
