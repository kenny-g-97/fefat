import { useQuery } from "@tanstack/react-query"
import { catalogQuery, isSyncing, type SyncCover } from "@/api/catalog"
import { Panel } from "@/ui/panel"
import {
  type CatalogProduct,
  catalogLine,
  type ImportedDataset,
  importedDatasets,
  notImported,
} from "./datasets"
import { ImportedHead, ImportedRow } from "./ImportedRow"
import { QueryBody } from "./QueryBody"

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
      <ImportedHead />
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
