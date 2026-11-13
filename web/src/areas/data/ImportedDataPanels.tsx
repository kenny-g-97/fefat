import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { cn } from "cn"
import { ArrowRight } from "lucide-react"
import { catalogQuery, isSyncing, type SyncCover } from "@/api/catalog"
import { IdentityChip } from "@/ui/identity-chip"
import { Panel } from "@/ui/panel"
import {
  type CatalogProduct,
  catalogLine,
  type ImportedDataset,
  importedDatasets,
  notImported,
} from "./datasets"
import { QualityBadge } from "./QualityBadge"
import { QueryBody } from "./QueryBody"

// shortcut: fixed tracks fit a root of 12 characters and a provider of 13 on one line, longer
// ones wrap; content-sized tracks through subgrid once real stores outgrow them.
const COLUMNS =
  "grid grid-cols-[6.5rem_7rem_minmax(0,1fr)_5.5rem_5.5rem_5.5rem_1rem] items-center gap-x-4 border px-2"

/** The data the trader imported, an instrument's from one provider in each row, which opens its
 * dataset's page, and under it the catalog's products that hold no data yet, both from
 * `GET /v1/catalog` (web/DESIGN.md, Patterns, Link rows). */
export function ImportedDataPanels({ syncs }: Readonly<{ syncs: SyncCover }>) {
  const catalog = useQuery(catalogQuery)
  const missing = catalog.status === "success" ? notImported(catalog.data) : []
  return (
    <>
      <Panel
        title="Imported data"
        description="An instrument's data from one provider in each row, with how clean it is"
      >
        <QueryBody query={catalog}>
          {(status) => (
            <ImportedRows datasets={importedDatasets(status)} syncs={syncs} />
          )}
        </QueryBody>
      </Panel>
      {missing.length > 0 && <NotImported products={missing} />}
    </>
  )
}

function ImportedRows({
  datasets,
  syncs,
}: Readonly<{ datasets: readonly ImportedDataset[]; syncs: SyncCover }>) {
  if (datasets.length === 0) {
    return (
      <p className="text-foreground-secondary">
        No data imported yet. Import data, above, brings your own files in.
      </p>
    )
  }
  return (
    <div className="-mx-2 flex flex-col gap-1">
      <div className={cn(COLUMNS, "h-10 border-transparent border-b-border")}>
        <span data-slot="list-head">Instrument</span>
        <span data-slot="list-head">Provider</span>
        <span data-slot="list-head">Data</span>
        <span data-slot="list-head" className="text-right">
          From
        </span>
        <span data-slot="list-head" className="text-right">
          To
        </span>
        <span data-slot="list-head">Quality</span>
      </div>
      <ul className="flex flex-col gap-1">
        {datasets.map((dataset) => (
          <li key={`${dataset.root} ${dataset.provider}`}>
            <ImportedRow
              dataset={dataset}
              syncing={isSyncing(syncs, dataset.root)}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

function ImportedRow({
  dataset,
  syncing,
}: Readonly<{ dataset: ImportedDataset; syncing: boolean }>) {
  const figure = "text-right text-foreground-secondary"
  return (
    <Link
      to="/data/dataset"
      search={{ instrument: dataset.root, provider: dataset.provider }}
      data-slot="row-link"
      data-testid="imported-row"
      className={cn(
        COLUMNS,
        "group min-h-10 rounded-xl border-transparent py-2 wrap-anywhere hover:border-border hover:bg-muted"
      )}
    >
      <span
        data-testid="imported-root"
        className="font-medium text-foreground group-hover:text-brand"
      >
        {dataset.root}
      </span>
      <span>
        <IdentityChip testId="provider-chip">{dataset.provider}</IdentityChip>
      </span>
      <span data-testid="imported-kinds" className="text-foreground-secondary">
        {dataset.kinds}
      </span>
      <span data-testid="imported-from" className={figure}>
        {dataset.from}
      </span>
      <span data-testid="imported-to" className={figure}>
        <span className="sr-only">to </span>
        {dataset.to}
      </span>
      <span>
        <QualityBadge standing={syncing ? "checking" : dataset.quality} />
      </span>
      <ArrowRight
        aria-hidden="true"
        className="size-4 text-foreground-secondary"
      />
    </Link>
  )
}

function NotImported({
  products,
}: Readonly<{ products: readonly CatalogProduct[] }>) {
  return (
    <Panel
      title="Not imported yet"
      description="The products of FEAT's catalog that hold no data, each with the source it recommends"
    >
      <ul className="flex flex-col gap-2">
        {products.map((product) => (
          <li
            key={product.root}
            data-testid="not-imported"
            className="flex items-baseline gap-3"
          >
            <span className="w-26 shrink-0 font-medium text-foreground">
              {product.root}
            </span>
            <span className="text-xs text-muted-foreground">
              {catalogLine(product)}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}
