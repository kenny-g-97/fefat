import { useQuery } from "@tanstack/react-query"
import { useSearch } from "@tanstack/react-router"
import {
  catalogQuery,
  isSyncing,
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
  chartTimeframe,
  type ImportedDataset,
  importedDatasets,
} from "./datasets"
import { DatasetTable } from "./DatasetTable"
import { QualityPanel } from "./QualityPanel"
import { QueryBody } from "./QueryBody"

/** A dataset's page (step 5.4; web/DESIGN.md, Patterns, Dataset page): an instrument's data
 * from one provider, the two named in the address, as a row of the Data page's list opens it:
 * what the store holds of it, with its chart, and its quality, which Check quality checks again
 * as a job, a catalog sync of the instrument and so of every provider's data of it. An address
 * that names no data FEAT holds says so. */
export function DatasetPage() {
  const shown = useSearch({ from: "/_shell/data/dataset" })
  const catalog = useQuery(catalogQuery)
  const syncs = useSyncCover()
  const sync = useCatalogSync()
  const dataset =
    catalog.data === undefined
      ? undefined
      : importedDatasets(catalog.data).find(
          (each) =>
            each.root === shown.instrument && each.provider === shown.provider
        )
  const syncing = dataset !== undefined && isSyncing(syncs, dataset.root)
  return (
    <Page
      title={shown.instrument === undefined ? "Dataset" : shown.instrument}
      description={
        dataset === undefined
          ? undefined
          : `What FEAT holds of ${dataset.root} from ${dataset.provider}, and how clean it is`
      }
      back={<BackLink to="/data">Back to Data</BackLink>}
      action={
        dataset === undefined ? undefined : (
          <Button
            variant="ghost"
            disabled={syncing || sync.isPending}
            onClick={() => sync.mutate(dataset.root)}
          >
            Check quality
          </Button>
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
              <QualityPanel dataset={dataset} syncing={syncing} />
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
            History from {dataset.product.history_from},{" "}
            {dataset.product.recommended_source} recommended
          </p>
        )}
      </div>
    </Panel>
  )
}

function NoSuchDataset({ shown }: Readonly<{ shown: DatasetSearch }>) {
  const named =
    shown.instrument === undefined || shown.provider === undefined
      ? "This address names no instrument and provider."
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
