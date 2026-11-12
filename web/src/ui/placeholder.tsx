import type { ReactNode } from "react"
import { Page } from "@/ui/page"

/** A page not built yet (web/DESIGN.md, Patterns): what it will hold, under its title, and that
 * it is not built yet; never invented data. */
export function PlaceholderPage({
  title,
  purpose,
  back,
}: Readonly<{ title: string; purpose: string; back?: ReactNode }>) {
  return (
    <Page title={title} description={purpose} back={back}>
      <p className="text-xs text-muted-foreground">Not built yet</p>
    </Page>
  )
}
