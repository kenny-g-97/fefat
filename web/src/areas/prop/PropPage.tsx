import { Page } from "@/ui/page"
import { Placeholder } from "@/ui/placeholder"

/** The Prop page, a placeholder until the step that builds it. */
export function PropPage() {
  return (
    <Page title="Prop">
      <Placeholder purpose="Replay a strategy's trades against a prop firm's rules." />
    </Page>
  )
}
