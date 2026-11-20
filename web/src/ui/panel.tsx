import { type ReactNode, type Ref, useId } from "react"
import { cn } from "cn"

type PanelProps = Readonly<{
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
  ref?: Ref<HTMLElement>
  tabIndex?: number
  children: ReactNode
}>

/** A card (web/DESIGN.md, Patterns): a region named by its title at 16 px, with an optional
 * one-line description and action, then its content, on the card surface with a hairline. A
 * card its page focuses, as the result of an action shown away from its button, takes `ref` and
 * a `tabIndex` of -1, so that the region a screen reader names is what takes the focus. */
export function Panel({
  title,
  description,
  action,
  className,
  ref,
  tabIndex,
  children,
}: PanelProps) {
  const heading = useId()
  return (
    <section
      ref={ref}
      tabIndex={tabIndex}
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
