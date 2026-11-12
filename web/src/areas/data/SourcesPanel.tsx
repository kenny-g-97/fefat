import { useQuery } from "@tanstack/react-query"
import { sourcesQuery } from "@/api/catalog"
import { Panel } from "@/ui/panel"
import { QueryBody } from "./QueryBody"
import { SourceRow } from "./SourceRow"

/** The source guide FEAT ships (`GET /v1/sources`): every source of market data, as researched
 * on the day it names, a disclosure row each. */
export function SourcesPanel() {
  const sources = useQuery(sourcesQuery)
  return (
    <Panel
      title="Sources"
      description="Where your data can come from: what each source offers and costs, and its terms"
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
  )
}
