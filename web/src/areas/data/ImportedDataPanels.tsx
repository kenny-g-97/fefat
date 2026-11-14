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
} from "./datasets"
import { ImportedFilterBar } from "./ImportedFilterBar"
import {
  drawnRow,
  filterChoices,
  type ImportedFilters,
  KNOWN_VALUES,
  matching,
  NO_FILTERS,
} from "./imported-filters"
import { ImportedHead, ImportedRow } from "./ImportedRow"
import { QueryBody } from "./QueryBody"

/** The data the trader imported, an instrument's from one provider in each row, which opens its
 * dataset's page, under its search and its dropdowns, and under it the catalog's products that
 * hold no data yet, both from `GET /v1/catalog` (web/DESIGN.md, Patterns, Link rows). What the
 * search and the dropdowns ask is the page's alone, in its memory: it outlives a catalog that
 * could not be read again, and leaving the page clears it. */
export function ImportedDataPanels({ syncs }: Readonly<{ syncs: SyncCover }>) {
  const catalog = useQuery(catalogQuery)
  const [filters, setFilters] = useState(NO_FILTERS)
  const missing = catalog.status === "success" ? notImported(catalog.data) : []
  return (
    <>
      <Panel
        title="Imported data"
        description="An instrument's data from one provider in each row, with how clean it is"
      >
        <QueryBody query={catalog}>
          {(status) => (
            <ImportedList
              datasets={importedDatasets(status)}
              syncs={syncs}
              filters={filters}
              onFilter={setFilters}
            />
          )}
        </QueryBody>
      </Panel>
      {missing.length > 0 && <NotImported products={missing} />}
    </>
  )
}

type ImportedListProps = Readonly<{
  datasets: readonly ImportedDataset[]
  syncs: SyncCover
  filters: ImportedFilters
  onFilter: (filters: ImportedFilters) => void
}>

/** The rows that the search and the dropdowns keep, or what says that they keep none. */
function ImportedList({
  datasets,
  syncs,
  filters,
  onFilter,
}: ImportedListProps) {
  const search = useRef<HTMLInputElement>(null)
  if (datasets.length === 0) {
    return (
      <p className="text-foreground-secondary">
        No data imported yet. Import data, above, brings your own files in.
      </p>
    )
  }
  const rows = datasets.map((dataset) => drawnRow(dataset, syncs))
  const shown = matching(rows, filters)
  return (
    <div className="flex flex-col gap-5">
      <ImportedFilterBar
        filters={filters}
        choices={filterChoices(rows, filters, KNOWN_VALUES)}
        search={search}
        onChange={onFilter}
      />
      {/* On one line, as tall as the rows' header, which comes back in its place: the button
          leaves under the pointer, and a second click must land on nothing that opens, so in a
          narrow card the message wraps and the button never drops under it. The message's place
          stays in the page, so that a screen reader hears it arrive. */}
      <div
        className={
          shown.length === 0 ? "flex min-h-10 items-center gap-3" : "sr-only"
        }
      >
        <p role="status" className="text-foreground-secondary">
          {shown.length === 0 && "No imported data matches the filters."}
        </p>
        {shown.length === 0 && (
          <Button
            variant="ghost"
            className="shrink-0"
            onClick={() => {
              onFilter(NO_FILTERS)
              // The button leaves with its message, and the focus would go nowhere.
              search.current?.focus()
            }}
          >
            Clear filters
          </Button>
        )}
      </div>
      {shown.length > 0 && (
        <div className="-mx-2 flex flex-col gap-1">
          <ImportedHead />
          <ul className="flex flex-col gap-1">
            {shown.map((row) => (
              <li key={`${row.instrument} ${row.provider}`}>
                <ImportedRow row={row} />
              </li>
            ))}
          </ul>
        </div>
      )}
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
