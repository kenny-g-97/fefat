import { cn } from "cn"
import type { ReactNode } from "react"

type StatProps = Readonly<{
  label: string
  value: ReactNode
  detail?: ReactNode
  tone?: "positive" | "negative"
  testId: string
}>

/** A stat card (web/DESIGN.md, Patterns, Stat card), one of a `dl`: its figure at 24 px in bold,
 * in the colour of its sign where it is money, its label under it, and one line of what the
 * figure is out of. The label comes first in the document, so that a screen reader names the
 * figure before reading it. */
export function Stat({ label, value, detail, tone, testId }: StatProps) {
  return (
    <div
      data-testid={testId}
      className="flex flex-col rounded-xl border bg-card p-5 shadow-raised"
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
      </dd>
      {detail !== undefined && (
        <dd className="order-3 mt-1 text-xs text-muted-foreground">{detail}</dd>
      )}
    </div>
  )
}
