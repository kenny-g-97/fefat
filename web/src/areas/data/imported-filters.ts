/** A row of the imported data as its filters read it: the words its cells show. */
export type ListedRow = Readonly<{
  instrument: string
  provider: string
  type: string
  data: string
  from: string
  to: string
  quality: string
}>

/** A column of the list that a dropdown filters. */
export type FilterColumn = "instrument" | "provider" | "type" | "quality"

/** What the trader asks of the list: the words typed in its search, and for each column the
 * value its rows must show, or none. */
export type ImportedFilters = Readonly<
  { search: string } & Record<FilterColumn, string | null>
>

/** The columns a dropdown filters, in the list's order. */
export const FILTER_COLUMNS: readonly FilterColumn[] = [
  "instrument",
  "provider",
  "type",
  "quality",
]

/** Nothing asked: every row shows. */
export const NO_FILTERS: ImportedFilters = {
  search: "",
  instrument: null,
  provider: null,
  type: null,
  quality: null,
}

/** The rows that show each column's chosen value and hold every word of the search, each word
 * in some cell, capitals ignored. */
export function matching<Row extends ListedRow>(
  rows: readonly Row[],
  filters: ImportedFilters
): readonly Row[] {
  const words = filters.search
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word !== "")
  return rows.filter(
    (row) =>
      FILTER_COLUMNS.every(
        (column) => filters[column] === null || row[column] === filters[column]
      ) &&
      words.every((word) =>
        cellsOf(row).some((cell) => cell.toLowerCase().includes(word))
      )
  )
}

/** Each column's values among `rows`, each once in the list's order, for its dropdown; a value
 * chosen that no row shows any more stays, last, so that its dropdown still names it. */
export function filterChoices(
  rows: readonly ListedRow[],
  filters: ImportedFilters
): Readonly<Record<FilterColumn, readonly string[]>> {
  const of = (column: FilterColumn): readonly string[] => {
    const shown = [...new Set(rows.map((row) => row[column]))]
    const chosen = filters[column]
    return chosen === null || shown.includes(chosen)
      ? shown
      : [...shown, chosen]
  }
  return {
    instrument: of("instrument"),
    provider: of("provider"),
    type: of("type"),
    quality: of("quality"),
  }
}

function cellsOf(row: ListedRow): readonly string[] {
  return [
    row.instrument,
    row.provider,
    row.type,
    row.data,
    row.from,
    row.to,
    row.quality,
  ]
}
