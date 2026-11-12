import { cn } from "cn"
import type { ReactNode } from "react"

type PageProps = Readonly<{
  title: string
  description?: string
  back?: ReactNode
  fill?: boolean
  children: ReactNode
}>

/** A page of the work area (web/DESIGN.md, Patterns): its tab's title, a header with the page
 * title and its one-line description, then the content, padded 32 px and at most 1600 px wide.
 * A page reached from its area's page leads `back` there from above its title. A page that
 * `fill`s, such as a chart's, takes the window's height under the top bar, down to the least it
 * reads at, so that its content grows into the rest. */
export function Page({
  title,
  description,
  back,
  fill = false,
  children,
}: PageProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full max-w-400 p-8",
        fill && "flex h-[calc(100dvh-4.5rem)] min-h-144 flex-col"
      )}
    >
      <title>{`${title} – FEAT`}</title>
      <header className="mb-8 flex flex-col gap-1">
        {back !== undefined && <div className="mb-1 flex">{back}</div>}
        <h1 className="text-title">{title}</h1>
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
