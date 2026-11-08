import type { ReactNode } from "react"

type PageProps = Readonly<{
  title: string
  description?: string
  children: ReactNode
}>

/** A page of the work area (web/DESIGN.md, Patterns): its tab's title, a header with the page
 * title and its one-line description, then the content, padded 32 px and at most 1600 px wide. */
export function Page({ title, description, children }: PageProps) {
  return (
    <div className="mx-auto w-full max-w-400 p-8">
      <title>{`${title} – FEAT`}</title>
      <header className="mb-8 flex flex-col gap-1">
        <h1 className="text-title">{title}</h1>
        {description !== undefined && (
          <p className="max-w-2xl text-foreground-secondary">{description}</p>
        )}
      </header>
      {children}
    </div>
  )
}
