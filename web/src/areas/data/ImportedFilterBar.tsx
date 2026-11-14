import type { Ref } from "react"
import { Input } from "@/ui/input"
import {
  FILTER_COLUMNS,
  type FilterColumn,
  type ImportedFilters,
} from "./imported-filters"
import { Choice, Picker } from "./Picker"

/** The dropdowns' choice that asks nothing of its column: no folder name holds parentheses
 * (`fefat.market.layout.FolderName`), nor does a type or a quality, as for the chart's
 * recommended provider. */
const ALL = "(all)"

const LABELS: Readonly<Record<FilterColumn, string>> = {
  instrument: "Instrument",
  provider: "Provider",
  type: "Type",
  quality: "Quality",
}

type ImportedFilterBarProps = Readonly<{
  filters: ImportedFilters
  choices: Readonly<Record<FilterColumn, readonly string[]>>
  search: Ref<HTMLInputElement>
  onChange: (filters: ImportedFilters) => void
}>

/** The list's search and its dropdowns, one for each column that holds few values
 * (web/DESIGN.md, Patterns, Link rows): a word typed and a value chosen narrow the rows at
 * once. The dropdowns are wider than the chart's, for a provider of 13 characters. */
export function ImportedFilterBar({
  filters,
  choices,
  search,
  onChange,
}: ImportedFilterBarProps) {
  return (
    <div
      role="group"
      aria-label="Filter imported data"
      className="flex flex-wrap items-end gap-4"
    >
      <Choice id="imported-search" label="Search" className="min-w-40 flex-1">
        <Input
          id="imported-search"
          ref={search}
          type="search"
          autoComplete="off"
          value={filters.search}
          onChange={(event) =>
            onChange({ ...filters, search: event.target.value })
          }
        />
      </Choice>
      {FILTER_COLUMNS.map((column) => {
        const chosen = filters[column]
        return (
          <Choice key={column} id={`imported-${column}`} label={LABELS[column]}>
            <Picker
              id={`imported-${column}`}
              className="w-42"
              value={chosen === null ? ALL : chosen}
              options={[
                { value: ALL, label: "All" },
                ...choices[column].map((value) => ({ value, label: value })),
              ]}
              onChange={(value) =>
                onChange({ ...filters, [column]: value === ALL ? null : value })
              }
            />
          </Choice>
        )
      })}
    </div>
  )
}
