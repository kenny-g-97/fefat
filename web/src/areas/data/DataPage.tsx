import { Page } from "@/ui/page"
import { Placeholder } from "@/ui/placeholder"

/** The Data page, a placeholder until the step that builds it. */
export function DataPage() {
  return (
    <Page title="Data">
      <Placeholder purpose="Import market data from your own sources, and check its quality." />
    </Page>
  )
}
