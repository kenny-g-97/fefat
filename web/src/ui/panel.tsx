import { useId, type ReactNode } from "react"
import { cn } from "cn"

type PanelProps = Readonly<{
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
  children: ReactNode
}>

/** A card (web/DESIGN.md, Patterns): a region named by its title at 16 px, with an optional
 * one-line description and action, then its content, on the card surface with a hairline. */
export function Panel({
  title,
  description,
  action,
  className,
  children,
}: PanelProps) {
  const heading = useId()
  return (
    <section
      aria-labelledby={heading}
      className={cn(
        "flex flex-col gap-5 rounded-xl border bg-card p-6 shadow-raised",
        className
      )}
    >
      <header className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id={heading} className="text-base font-semibold">
            {title}
          </h2>
          {description !== undefined && (
            <p className="text-foreground-secondary">{description}</p>
          )}
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}
