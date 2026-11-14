import { useQuery } from "@tanstack/react-query"
import { sourcesQuery } from "@/api/catalog"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { BackLink } from "@/ui/text-link"
import { QueryBody } from "./QueryBody"
import { SourceRow } from "./SourceRow"

/** The source guide FEAT ships, on a page of its own (`GET /v1/sources`): every source of
 * market data, as researched on the day it names, a disclosure row each, with an Import where
 * FEAT reads its files; the Data page lists the sources the trader imported from alone. */
export function SourcesPage() {
  const sources = useQuery(sourcesQuery)
  return (
    <Page
      title="Sources"
      description="Where your data can come from: what each source offers and costs, and its terms"
      back={<BackLink to="/data">Back to Data</BackLink>}
    >
      <Panel
        title="Source guide"
        description="Each source FEAT has researched, with the file layouts it imports from it"
      >
        <QueryBody query={sources}>
          {(guide) => (
            <div className="flex flex-col">
              <p className="pb-2 text-xs text-muted-foreground">
                Researched on {guide.researched_on}
              </p>
              {guide.sources.map((source) => (
                <SourceRow key={source.id} source={source} />
              ))}
            </div>
          )}
        </QueryBody>
      </Panel>
    </Page>
  )
}
