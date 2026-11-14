import { cn } from "cn"
import { type Standing, STANDING_LABELS } from "./datasets"

const TONES: Readonly<Record<Standing, string>> = {
  checking: "border-brand-soft-border bg-brand-soft text-brand-soft-foreground",
  flagged: "border-transparent bg-negative-soft text-negative",
  clean: "border-transparent bg-accent text-foreground",
  unchecked: "border-transparent bg-accent text-foreground",
  stale: "border-transparent bg-accent text-foreground",
}

/** A quality's badge (web/DESIGN.md, Patterns, Quality badge): Checking while a sync runs, on
 * the active item's soft fill; Flagged in the negative on its soft fill, an alert; the others
 * on the hover step in heading text, since green marks a profit alone. */
export function QualityBadge({ standing }: Readonly<{ standing: Standing }>) {
  return (
    <span
      data-testid="quality-badge"
      className={cn(
        "rounded-xl border px-2 py-0.5 text-xs font-semibold",
        TONES[standing]
      )}
    >
      {STANDING_LABELS[standing]}
    </span>
  )
}
