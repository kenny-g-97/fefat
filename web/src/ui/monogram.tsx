import { cn } from "cn"

/** FEFAT's placeholder mark until Phase 14: an F in the accent on the brand's soft tile, with the
 * one radius of the Contemporary skill, the same drawing as `public/favicon.svg`. */
export function Monogram({ className }: Readonly<{ className?: string }>) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <rect
        width="32"
        height="32"
        rx="9.6"
        className="fill-brand-soft stroke-border"
      />
      <path
        d="M11 8h11v3.5h-7.25v3.25h6.25v3.5h-6.25V24H11z"
        className="fill-primary"
      />
    </svg>
  )
}
