import { cn } from "cn"
import type { StoredDataset } from "@/api/catalog"

/** How a dataset's quality stands: as its report reads, or being checked while a sync covers
 * its instrument. */
type Standing = StoredDataset["quality"] | "checking"

const BADGES: Readonly<
  Record<Standing, Readonly<{ label: string; tone: string }>>
> = {
  checking: {
    label: "Checking",
    tone: "border-brand-soft-border bg-brand-soft text-brand-soft-foreground",
  },
  flagged: {
    label: "Flagged",
    tone: "border-transparent bg-negative-soft text-negative",
  },
  clean: {
    label: "Clean",
    tone: "border-transparent bg-accent text-foreground",
  },
  unchecked: {
    label: "Unchecked",
    tone: "border-transparent bg-accent text-foreground",
  },
  stale: {
    label: "Stale",
    tone: "border-transparent bg-accent text-foreground",
  },
}

/** A quality's badge (web/DESIGN.md, Patterns, Quality badge): Checking while a sync runs, on
 * the active item's soft fill; Flagged in the negative on its soft fill, an alert; the others
 * on the hover step in heading text, since green marks a profit alone. */
export function QualityBadge({ standing }: Readonly<{ standing: Standing }>) {
  const badge = BADGES[standing]
  return (
    <span
      data-testid="quality-badge"
      className={cn(
        "rounded-xl border px-2 py-0.5 text-xs font-semibold",
        badge.tone
      )}
    >
      {badge.label}
    </span>
  )
}
