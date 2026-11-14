import { useQuery } from "@tanstack/react-query"
import { catalogQuery, sourcesQuery, type SyncCover } from "@/api/catalog"
import { Panel } from "@/ui/panel"
import { TextLink } from "@/ui/text-link"
import { type ImportedDataset, importedDatasets, standing } from "./datasets"
import { DisclosureRow } from "./DisclosureRow"
import { ImportedRow } from "./ImportedRow"
import { type ImportedSource, importedSources } from "./imported-sources"
import { QueryBody } from "./QueryBody"

/** The sources the trader imported from (web/DESIGN.md, Patterns, Disclosure row): the guide's
 * sources whose presets the imported data is stored under, and the providers it lists under
 * none, each opening the rows held from it; under them, the way to the guide's own page, which
 * stays where the sources cannot be read. */
export function ImportedSourcesPanel({
  syncs,
}: Readonly<{ syncs: SyncCover }>) {
  const guide = useQuery(sourcesQuery)
  const catalog = useQuery(catalogQuery)
  return (
    <Panel
      title="Sources"
      description="The sources you imported from, each with the rows you hold from it"
    >
      <div className="flex flex-col gap-5">
        <QueryBody query={guide}>
          {({ sources }) => (
            <QueryBody query={catalog}>
              {(status) => (
                <ImportedSources
                  sources={importedSources(importedDatasets(status), sources)}
                  syncs={syncs}
                />
              )}
            </QueryBody>
          )}
        </QueryBody>
        <TextLink to="/data/sources" className="self-start">
          All sources
        </TextLink>
      </div>
    </Panel>
  )
}

type ImportedSourcesProps = Readonly<{
  sources: readonly ImportedSource<ImportedDataset>[]
  syncs: SyncCover
}>

function ImportedSources({ sources, syncs }: ImportedSourcesProps) {
  if (sources.length === 0) {
    return (
      <p className="text-foreground-secondary">
        No source yet. The sources of what you import are listed here.
      </p>
    )
  }
  return (
    <div className="flex flex-col">
      {sources.map((source) => (
        <DisclosureRow
          key={source.key}
          testId="imported-source"
          name={source.name}
          note={source.note}
        >
          <ul className="-mx-2 flex flex-col gap-1 pt-1 pb-3">
            {source.rows.map((dataset) => (
              <li key={`${dataset.root} ${dataset.provider}`}>
                <ImportedRow
                  dataset={dataset}
                  standing={standing(dataset, syncs)}
                />
              </li>
            ))}
          </ul>
        </DisclosureRow>
      ))}
    </div>
  )
}
