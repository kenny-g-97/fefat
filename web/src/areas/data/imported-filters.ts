import type { SyncCover } from "@/api/catalog"
import {
  type ImportedDataset,
  type Standing,
  standing,
  STANDING_LABELS,
  TYPE_LABELS,
} from "./datasets"

/** A row of the imported data as its filters read it: the words its cells show. */
export type ListedRow = Readonly<{
  instrument: string
  provider: string
  type: string
  kinds: readonly string[]
  from: string
  to: string
  quality: string
}>

/** A row as the list draws it: the words its filters read, and how its quality stands, which
 * gives its badge its tone. */
export type DrawnRow = ListedRow & Readonly<{ standing: Standing }>

/** A column of the list that a dropdown filters. */
export type FilterColumn = "instrument" | "provider" | "type" | "quality"

/** What the trader asks of the list: the words typed in its search, and for each column the
 * value its rows must show, or none. */
export type ImportedFilters = Readonly<
  { search: string } & Record<FilterColumn, string | null>
>

/** A dropdown's choices for each column. */
export type FilterChoices = Readonly<Record<FilterColumn, readonly string[]>>

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

/** The columns of few known values, each in its own order, which its dropdown keeps whatever
 * the rows' order: a type, and how a quality stands. */
export const KNOWN_VALUES: Partial<FilterChoices> = {
  type: Object.values(TYPE_LABELS),
  quality: Object.values(STANDING_LABELS),
}

/** `dataset`'s row while `syncs` are under way: the one place its cells' words are made, for
 * the list to draw and its filters to read. */
export function drawnRow(dataset: ImportedDataset, syncs: SyncCover): DrawnRow {
  const stands = standing(dataset, syncs)
  return {
    instrument: dataset.root,
    provider: dataset.provider,
    type: TYPE_LABELS[dataset.type],
    kinds: dataset.kinds,
    from: dataset.from,
    to: dataset.to,
    quality: STANDING_LABELS[stands],
    standing: stands,
  }
}

/** The rows that show each column's chosen value and hold every word of the search, each word
 * in some cell, capitals ignored. A comma parts words as a space does, since the list draws one
 * between two kinds of data, which are two cells here. */
export function matching<Row extends ListedRow>(
  rows: readonly Row[],
  filters: ImportedFilters
): readonly Row[] {
  const words = filters.search
    .toLowerCase()
    .split(/[\s,]+/)
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

/** Each column's values among `rows`, each once, for its dropdown: in the list's order, or in
 * the column's own where `known` gives one, a value it does not name after those it names. A
 * value chosen that no row shows any more stays, so that its dropdown still names it: in its
 * place among a known column's, else last. */
export function filterChoices(
  rows: readonly ListedRow[],
  filters: ImportedFilters,
  known: Partial<FilterChoices>
): FilterChoices {
  const of = (column: FilterColumn): readonly string[] => {
    const shown = [...new Set(rows.map((row) => row[column]))]
    const chosen = filters[column]
    const offered =
      chosen === null || shown.includes(chosen) ? shown : [...shown, chosen]
    const order = known[column]
    return order === undefined
      ? offered
      : [
          ...order.filter((value) => offered.includes(value)),
          ...offered.filter((value) => !order.includes(value)),
        ]
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
    ...row.kinds,
    row.from,
    row.to,
    row.quality,
  ]
}
