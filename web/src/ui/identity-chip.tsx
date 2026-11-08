import type { ReactNode } from "react"

/** FEFAT's signature (web/DESIGN.md, Direction): an identity read exactly, such as a version,
 * a hash, or a token's name, in a 12 px tag on the hairline step, which reads on the sidebar
 * and on a card alike. */
export function IdentityChip({
  children,
  testId,
}: Readonly<{ children: ReactNode; testId?: string }>) {
  return (
    <span
      data-testid={testId}
      className="inline-block rounded-xl bg-accent px-2 py-0.5 text-xs text-foreground-secondary"
    >
      {children}
    </span>
  )
}
