import { useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { catalogQuery, type SyncCover } from "@/api/catalog"
import { Button } from "@/ui/button"
import { Panel } from "@/ui/panel"
import {
  type CatalogProduct,
  catalogLine,
  type ImportedDataset,
  importedDatasets,
  notImported,
  type Standing,
  standing,
  STANDING_LABELS,
  TYPE_LABELS,
} from "./datasets"
import { ImportedFilterBar } from "./ImportedFilterBar"
import {
  filterChoices,
  type ListedRow,
  matching,
  NO_FILTERS,
} from "./imported-filters"
import { ImportedHead, ImportedRow } from "./ImportedRow"
import { QueryBody } from "./QueryBody"

/** A row as the list draws it and as its filters read it: the words of its cells. */
type Listed = ListedRow &
  Readonly<{ dataset: ImportedDataset; standing: Standing }>

/** The data the trader imported, an instrument's from one provider in each row, which opens its
 * dataset's page, under its search and its dropdowns, and under it the catalog's products that
 * hold no data yet, both from `GET /v1/catalog` (web/DESIGN.md, Patterns, Link rows). */
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
            <ImportedList datasets={importedDatasets(status)} syncs={syncs} />
          )}
        </QueryBody>
      </Panel>
      {missing.length > 0 && <NotImported products={missing} />}
    </>
  )
}

/** The rows that the search and the dropdowns keep. What they ask is the page's alone, in its
 * memory: leaving the page clears it. */
function ImportedList({
  datasets,
  syncs,
}: Readonly<{ datasets: readonly ImportedDataset[]; syncs: SyncCover }>) {
  const [filters, setFilters] = useState(NO_FILTERS)
  const search = useRef<HTMLInputElement>(null)
  if (datasets.length === 0) {
    return (
      <p className="text-foreground-secondary">
        No data imported yet. Import data, above, brings your own files in.
      </p>
    )
  }
  const rows = datasets.map((dataset) => listed(dataset, syncs))
  const shown = matching(rows, filters)
  return (
    <div className="flex flex-col gap-5">
      <ImportedFilterBar
        filters={filters}
        choices={filterChoices(rows, filters)}
        search={search}
        onChange={setFilters}
      />
      {shown.length === 0 ? (
        <div className="flex flex-col items-start gap-3">
          <p role="status" className="text-foreground-secondary">
            No imported data matches the search and the filters.
          </p>
          <Button
            variant="ghost"
            onClick={() => {
              setFilters(NO_FILTERS)
              // The button leaves with its message, and the focus would go nowhere.
              search.current?.focus()
            }}
          >
            Clear filters
          </Button>
        </div>
      ) : (
        <div className="-mx-2 flex flex-col gap-1">
          <ImportedHead />
          <ul className="flex flex-col gap-1">
            {shown.map((row) => (
              <li key={`${row.instrument} ${row.provider}`}>
                <ImportedRow dataset={row.dataset} standing={row.standing} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function listed(dataset: ImportedDataset, syncs: SyncCover): Listed {
  const stands = standing(dataset, syncs)
  return {
    dataset,
    standing: stands,
    instrument: dataset.root,
    provider: dataset.provider,
    type: TYPE_LABELS[dataset.type],
    data: dataset.kinds,
    from: dataset.from,
    to: dataset.to,
    quality: STANDING_LABELS[stands],
  }
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
