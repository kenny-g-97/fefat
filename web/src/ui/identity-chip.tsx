import type { ReactNode } from "react"

/** FEFAT's signature (web/DESIGN.md, Direction): an identity read exactly, such as a version,
 * a hash, or a token's name, in the monospace on the active surface. */
export function IdentityChip({
  children,
  testId,
}: Readonly<{ children: ReactNode; testId?: string }>) {
  return (
    <span
      data-testid={testId}
      className="inline-block rounded-sm border bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
    >
      {children}
    </span>
  )
}
