import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"

/** The tone of a row's aside: quiet, or the sign it gives (web/DESIGN.md, Principles), the
 * positive for an import's file that imports and the negative for a failure (D-105). */
export type AsideTone = "quiet" | "positive" | "negative"

const ASIDE_TONES: Readonly<Record<AsideTone, string>> = {
  quiet: "text-xs text-muted-foreground",
  positive: "text-positive",
  negative: "text-negative",
}

type DisclosureRowProps = Readonly<{
  testId: string
  name: string
  note?: string
  aside?: string
  asideTone?: AsideTone
  reason?: string | null
  children: ReactNode
}>

/** A row that opens in place (web/DESIGN.md, Patterns, Disclosure row): a 40 px summary of its
 * name, a note on it, and an aside at its right end in its tone, and under the name, where the
 * row gives one, the reason of a failure in the negative, which reads while the row is closed
 * (D-105); over what it discloses. Its chevron turns for its own row alone, not for one that
 * holds it. Its group is named, so that the rows it discloses, each a group of its own, answer
 * the pointer one at a time, where a group without a name would light them all while the
 * pointer is on any. */
export function DisclosureRow({
  testId,
  name,
  note,
  aside,
  asideTone = "quiet",
  reason = null,
  children,
}: DisclosureRowProps) {
  return (
    <details
      data-testid={testId}
      className="group/disclosure border-b last:border-b-0"
    >
      <summary className="-mx-2 flex min-h-10 cursor-pointer list-none gap-3 rounded-xl px-2 py-2.5">
        <ChevronRight className="mt-0.5 size-4 shrink-0 text-foreground-secondary transition-transform [details[open]>summary>&]:rotate-90" />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex min-h-5 items-center gap-3">
            <span className="font-medium text-foreground">{name}</span>
            {note !== undefined && (
              <span className="text-xs text-muted-foreground">{note}</span>
            )}
            {aside !== undefined && (
              <span
                className={`ml-auto shrink-0 ${ASIDE_TONES[asideTone]}`}
                data-testid={`${testId}-aside`}
              >
                {aside}
              </span>
            )}
          </span>
          {reason !== null && (
            <span className="text-negative" data-testid={`${testId}-reason`}>
              {reason}
            </span>
          )}
        </span>
      </summary>
      {children}
    </details>
  )
}
