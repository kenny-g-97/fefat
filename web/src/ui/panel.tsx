import type { ReactNode } from "react"
import { cn } from "cn"

type PanelProps = Readonly<{
  title: string
  action?: ReactNode
  className?: string
  children: ReactNode
}>

/** A raised panel with a hairline (web/DESIGN.md, Patterns): its title at 16 px, an optional
 * quiet action on the right, and its content. */
export function Panel({ title, action, className, children }: PanelProps) {
  return (
    <section
      className={cn(
        "flex flex-col gap-3 rounded-xl border bg-card p-5 shadow-raised",
        className
      )}
    >
      <header className="flex items-baseline justify-between gap-4">
        <h2 className="text-base font-medium">{title}</h2>
        {action}
      </header>
      {children}
    </section>
  )
}
