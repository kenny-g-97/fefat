import { cn } from "cn"
import { type Job, STATUS_LABELS } from "@/api/jobs"

/** Each status's badge: running on the active item's soft fill, a failure on the negative's,
 * and the rest on the hover step in heading text, since green marks a profit alone (the design
 * brief). */
const STATUS_TONES: Readonly<Record<Job["status"], string>> = {
  queued: "border-transparent bg-accent text-foreground",
  running: "border-brand-soft-border bg-brand-soft text-brand-soft-foreground",
  succeeded: "border-transparent bg-accent text-foreground",
  failed: "border-transparent bg-negative-soft text-negative",
  cancelled: "border-transparent bg-accent text-foreground",
  timed_out: "border-transparent bg-negative-soft text-negative",
}

type StatusBadgeProps = Readonly<{
  status: Job["status"]
  cancelling: boolean
  testId?: string
}>

/** A job's or a run's status as a badge (web/DESIGN.md, Patterns, Badges); a running one asked to
 * stop reads Cancelling. */
export function StatusBadge({ status, cancelling, testId }: StatusBadgeProps) {
  return (
    <span
      data-testid={testId}
      className={cn(
        "shrink-0 rounded-xl border px-2 py-0.5 text-xs font-semibold",
        STATUS_TONES[status]
      )}
    >
      {cancelling ? "Cancelling" : STATUS_LABELS[status]}
    </span>
  )
}
