import { PlaceholderPage } from "@/ui/placeholder"
import { BackLink } from "@/ui/text-link"

/** The import wizard's page, a placeholder until step 5.12 builds it: a source's Import leads
 * here with its preset. */
export function ImportPage() {
  return (
    <PlaceholderPage
      title="Import"
      purpose="Bring your own files in through a source's preset or a profile of your own"
      back={<BackLink to="/data">Back to Data</BackLink>}
    />
  )
}
