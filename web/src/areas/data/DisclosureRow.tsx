import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"

type DisclosureRowProps = Readonly<{
  testId: string
  name: string
  note: string
  aside?: string
  children: ReactNode
}>

/** A row that opens in place (web/DESIGN.md, Patterns, Disclosure row): a 40 px summary of its
 * name, a note on it, and an aside at its right end, over what it discloses. Its group is
 * named, so that the rows it discloses, each a group of its own, answer the pointer one at a
 * time, where a group without a name would light them all while the pointer is on any. */
export function DisclosureRow({
  testId,
  name,
  note,
  aside,
  children,
}: DisclosureRowProps) {
  return (
    <details
      data-testid={testId}
      className="group/disclosure border-b last:border-b-0"
    >
      <summary className="-mx-2 flex h-10 cursor-pointer list-none items-center gap-3 rounded-xl px-2">
        <ChevronRight className="size-4 shrink-0 text-foreground-secondary transition-transform group-open/disclosure:rotate-90" />
        <span className="font-medium text-foreground">{name}</span>
        <span className="text-xs text-muted-foreground">{note}</span>
        {aside !== undefined && (
          <span className="ml-auto text-xs text-muted-foreground">{aside}</span>
        )}
      </summary>
      {children}
    </details>
  )
}
