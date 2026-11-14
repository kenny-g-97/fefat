import { useQuery } from "@tanstack/react-query"
import { Link, useSearch } from "@tanstack/react-router"
import {
  catalogQuery,
  type StoredDataset,
  useCatalogSync,
  useSyncCover,
} from "@/api/catalog"
import { Button } from "@/ui/button"
import { IdentityChip } from "@/ui/identity-chip"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { BackLink, TextLink } from "@/ui/text-link"
import type { DatasetSearch } from "./chart-search"
import {
  catalogLine,
  chartTimeframe,
  type ImportedDataset,
  importedDatasets,
  standing,
} from "./datasets"
import { DatasetTable } from "./DatasetTable"
import { QualityPanel } from "./QualityPanel"
import { QueryBody } from "./QueryBody"
import { SpecificationPanel } from "./SpecificationPanel"

/** A dataset's page (step 5.4; web/DESIGN.md, Patterns, Dataset page): an instrument's data
 * from one provider, the two named in the address, as a row of the Data page's list opens it:
 * what the store holds of it, with its chart; its quality, which Check quality checks again as
 * a job, a catalog sync of the instrument and so of every provider's data of it; and the
 * instrument's specification. Import more data leads to the import page with the provider as
 * its preset, step 5.12's wizard. An address that names no data FEAT holds says so. */
export function DatasetPage() {
  const shown = useSearch({ from: "/_shell/data/dataset" })
  // Each dataset its own state: the route stays as the address goes from one to another, and a
  // check refused for one is no word about the next.
  return (
    <ShownDataset key={`${shown.instrument} ${shown.provider}`} shown={shown} />
  )
}

function ShownDataset({ shown }: Readonly<{ shown: DatasetSearch }>) {
  const catalog = useQuery(catalogQuery)
  const syncs = useSyncCover()
  const sync = useCatalogSync()
  // From an answer alone: once the catalog cannot be read again, its last answer shows nothing
  // to act on, as the cards show none.
  const dataset =
    catalog.status === "success"
      ? importedDatasets(catalog.data).find(
          (each) =>
            each.root === shown.instrument && each.provider === shown.provider
        )
      : undefined
  return (
    <Page
      title={
        shown.instrument === undefined || shown.provider === undefined
          ? "Dataset"
          : `${shown.instrument} from ${shown.provider}`
      }
      description={
        dataset === undefined
          ? undefined
          : "What FEAT holds of it, how clean it is, and its instrument's specification"
      }
      back={<BackLink to="/data">Back to Data</BackLink>}
      action={
        dataset === undefined ? undefined : (
          <>
            <Button
              variant="ghost"
              disabled={
                standing(dataset, syncs) === "checking" || sync.isPending
              }
              onClick={() => sync.mutate(dataset.root)}
            >
              Check quality
            </Button>
            <Button asChild>
              <Link to="/data/import" search={{ preset: dataset.provider }}>
                Import more data
              </Link>
            </Button>
          </>
        )
      }
    >
      <QueryBody query={catalog}>
        {() =>
          dataset === undefined ? (
            <NoSuchDataset shown={shown} />
          ) : (
            <div className="flex flex-col gap-6">
              {sync.error !== null && (
                <p role="alert" className="text-negative">
                  {sync.error.message}
                </p>
              )}
              <HeldPanel dataset={dataset} />
              <QualityPanel
                dataset={dataset}
                standing={standing(dataset, syncs)}
              />
              <SpecificationPanel root={dataset.root} />
            </div>
          )
        }
      </QueryBody>
    </Page>
  )
}

function HeldPanel({ dataset }: Readonly<{ dataset: ImportedDataset }>) {
  const [first] = dataset.stored
  return (
    <Panel
      title="Trades and bars"
      action={
        <TextLink
          to="/data/chart"
          search={{
            instrument: dataset.root,
            provider: dataset.provider,
            timeframe: chartTimeframe(dataset.stored),
          }}
        >
          Chart
        </TextLink>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <IdentityChip testId="provider-chip">{dataset.provider}</IdentityChip>
          <span className="text-xs text-muted-foreground">
            {provenance(first)}
          </span>
        </div>
        <DatasetTable datasets={dataset.stored} />
        {dataset.product !== null && (
          <p className="text-xs text-muted-foreground">
            {catalogLine(dataset.product)}
          </p>
        )}
      </div>
    </Panel>
  )
}

function NoSuchDataset({ shown }: Readonly<{ shown: DatasetSearch }>) {
  const named =
    shown.instrument === undefined || shown.provider === undefined
      ? "This address needs an instrument and a provider."
      : `FEAT holds no data of ${shown.instrument} from ${shown.provider}.`
  return (
    <p role="alert" className="text-negative">
      {named} Choose a row of Imported data on the Data page.
    </p>
  )
}

/** Where a dataset came from: imported or synced, and the last day a file of it came in. */
function provenance(dataset: StoredDataset): string {
  const origin = dataset.origin === "import" ? "Imported" : "Synced"
  return dataset.last_import === null
    ? origin
    : `${origin}, last on ${dataset.last_import}`
}
