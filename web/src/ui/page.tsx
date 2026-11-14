import { cn } from "cn"
import type { ReactNode } from "react"

type PageProps = Readonly<{
  title: string
  description?: string
  back?: ReactNode
  action?: ReactNode
  fill?: boolean
  children: ReactNode
}>

/** A page of the work area (web/DESIGN.md, Patterns): its tab's title, a header with the page
 * title and its one-line description, then the content, padded 32 px and at most 1600 px wide.
 * A page reached from its area's page leads `back` there from above its title, and a page's
 * `action`, its buttons, stands at the right end of the title's line. A page that `fill`s, such
 * as a chart's, is at least the window's height under the top bar, and never under the least it
 * reads at, so that its content grows into the rest; content with a height of its own, such as
 * a chart the trader made taller, lengthens the page, which keeps its padding under it. */
export function Page({
  title,
  description,
  back,
  action,
  fill = false,
  children,
}: PageProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full max-w-400 p-8",
        fill && "flex min-h-[max(calc(100dvh_-_4.5rem),36rem)] flex-col"
      )}
    >
      <title>{`${title} – FEAT`}</title>
      <header className="mb-8 flex flex-col gap-1">
        {back !== undefined && <div className="mb-1 flex">{back}</div>}
        <div className="flex items-center justify-between gap-4">
          <h1 className="min-w-0 text-title">{title}</h1>
          {action !== undefined && (
            <div className="flex shrink-0 items-center gap-2">{action}</div>
          )}
        </div>
        {description !== undefined && (
          <p className="max-w-2xl text-foreground-secondary">{description}</p>
        )}
      </header>
      {fill ? (
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      ) : (
        children
      )}
    </div>
  )
}
