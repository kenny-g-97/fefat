import type { ReactNode } from "react"

type PageProps = Readonly<{
  title: string
  actions?: ReactNode
  children: ReactNode
}>

/** A page of the work area (web/DESIGN.md, Patterns): its tab's title, a 56 px header with
 * the page title and any actions, and the content, 24 px from the edges and at most 1600 px
 * wide. */
export function Page({ title, actions, children }: PageProps) {
  return (
    <div className="mx-auto w-full max-w-400 px-6 pb-8">
      <title>{`${title} – FEFAT`}</title>
      <header className="flex h-14 items-center justify-between gap-4">
        <h1 className="text-xl font-medium">{title}</h1>
        {actions}
      </header>
      {children}
    </div>
  )
}
