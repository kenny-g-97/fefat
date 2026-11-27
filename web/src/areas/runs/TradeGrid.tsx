import { flexRender, type Header, useTable } from "@tanstack/react-table"
import type { VirtualItem } from "@tanstack/react-virtual"
import { cn } from "cn"
import { ArrowDown, ArrowUp } from "lucide-react"
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react"
import type { Trade, TradeSort } from "@/api/trades"
import { announceSelectedTrade } from "./selected-trade"
import {
  columnWidth,
  TRADE_TABLE_FEATURES,
  type TradeLook,
  tableColumns,
  tradeColumn,
} from "./trade-columns"
import { ROW_HEIGHT, useVirtualRows } from "./virtual-rows"

export type SortOrder = "asc" | "desc"

/** How many rows short of the last read the next page is asked for: a window's rows and more. */
const LOOKAHEAD = 50
/** The rem a card's 24 px of edge padding adds to its first and its last column, over the 8 px
 * of every cell. */
const EDGE = 1
const ARIA_SORT = { asc: "ascending", desc: "descending" } as const

type TradeGridProps = Readonly<{
  trades: readonly Trade[]
  total: number | null
  look: TradeLook
  visibility: Readonly<Record<string, boolean>>
  sort: TradeSort
  order: SortOrder
  onOrder: (sort: TradeSort, order: SortOrder) => void
  onNearEnd: () => void
}>

/** The trades read so far as a data grid (web/DESIGN.md, Patterns, Data grid): a card that
 * scrolls both ways, no taller than its rows, its header row and its entry column standing
 * still, only the rows near its view drawn, busy without rows while `total` is not known yet; a
 * row chosen by the pointer, Enter, or Space, or reached by the arrows, is the selected trade,
 * which `announceSelectedTrade` tells the page. */
export function TradeGrid({
  trades,
  total,
  look,
  visibility,
  sort,
  order,
  onOrder,
  onNearEnd,
}: TradeGridProps) {
  const box = useRef<HTMLDivElement>(null)
  const columns = useMemo(() => tableColumns(look), [look])
  const sorting = [{ id: sort, desc: order === "desc" }]
  const table = useTable({
    features: TRADE_TABLE_FEATURES,
    columns,
    data: trades,
    getRowId: (trade) => String(trade.trade),
    state: { sorting, columnVisibility: visibility },
    onSortingChange: (change) => {
      const next = (typeof change === "function" ? change(sorting) : change).at(
        0
      )
      const by = next === undefined ? null : tradeColumn(next.id).sort
      if (next !== undefined && by !== null) {
        onOrder(by.by, next.desc ? "desc" : "asc")
      }
    },
    manualSorting: true,
    enableSortingRemoval: false,
    enableMultiSort: false,
  })
  const { virtualizer, rows, above, below } = useVirtualRows(trades.length, box)
  const [selected, setSelected] = useState<number | null>(null)
  const [focusing, setFocusing] = useState<number | null>(null)
  const lastDrawn = rows.at(-1)
  useEffect(() => {
    if (
      lastDrawn !== undefined &&
      lastDrawn.index >= trades.length - LOOKAHEAD
    ) {
      onNearEnd()
    }
  }, [lastDrawn, trades.length, onNearEnd])
  useEffect(() => {
    const row =
      focusing === null
        ? null
        : box.current?.querySelector<HTMLElement>(`[data-index="${focusing}"]`)
    if (row !== null && row !== undefined) {
      row.focus({ preventScroll: true })
      setFocusing(null)
    }
  }, [focusing, rows])
  const choose = (index: number) => {
    const trade = trades.at(index)
    if (trade !== undefined) {
      setSelected(trade.trade)
      announceSelectedTrade(trade)
    }
  }
  const step = (event: KeyboardEvent, index: number) => {
    const to =
      event.key === "ArrowDown"
        ? index + 1
        : event.key === "ArrowUp"
          ? index - 1
          : null
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      choose(index)
    }
    if (to !== null && to >= 0 && to < trades.length) {
      event.preventDefault()
      choose(to)
      virtualizer.scrollToIndex(to, { align: "auto" })
      setFocusing(to)
    }
  }
  const selectedIndex = trades.findIndex((trade) => trade.trade === selected)
  const reachable = tabbableRow(rows, selectedIndex, virtualizer.scrollOffset)
  const headers = table.getHeaderGroups().at(0)?.headers ?? []
  const widths = edgeWidths(
    headers.map((header) => columnWidth(tradeColumn(header.column.id), look))
  )
  const modelRows = table.getRowModel().rows
  return (
    <div
      ref={box}
      data-slot="data-grid"
      data-testid="trade-grid"
      style={{ maxHeight: `${(trades.length + 1) * ROW_HEIGHT + 2}px` }}
      className="relative min-h-40 flex-[1_1_0px] overflow-auto rounded-xl border bg-card text-foreground-secondary shadow-raised"
    >
      <table
        role="grid"
        aria-label="Trades"
        aria-rowcount={total === null ? -1 : total + 1}
        aria-busy={total === null}
        className="table-fixed border-separate border-spacing-0"
        style={{ width: `max(100%, calc(${widths.join(" + ")}))` }}
      >
        <colgroup>
          {headers.map((header, index) => (
            <col key={header.id} style={{ width: widths[index] }} />
          ))}
        </colgroup>
        <thead data-slot="grid-head">
          <tr aria-rowindex={1}>
            {headers.map((header) => (
              <GridHead key={header.id} header={header} />
            ))}
          </tr>
        </thead>
        <tbody>
          {above > 0 && <tr aria-hidden="true" style={{ height: above }} />}
          {rows.map((drawn) => {
            const row = modelRows.at(drawn.index)
            return row === undefined ? null : (
              <tr
                key={row.id}
                data-slot="grid-row"
                data-testid="trade-row"
                data-index={drawn.index}
                aria-rowindex={drawn.index + 2}
                aria-selected={row.original.trade === selected}
                tabIndex={drawn.index === reachable ? 0 : -1}
                onClick={() => choose(drawn.index)}
                onKeyDown={(event) => step(event, drawn.index)}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className={cellLook(tradeColumn(cell.column.id).figure)}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            )
          })}
          {below > 0 && <tr aria-hidden="true" style={{ height: below }} />}
        </tbody>
      </table>
    </div>
  )
}

/** The visible columns' widths as CSS lengths, the first and the last widened by the card's
 * edge. */
function edgeWidths(widths: readonly string[]): string[] {
  return widths.map((width, index) => {
    const edges =
      (index === 0 ? EDGE : 0) + (index === widths.length - 1 ? EDGE : 0)
    return edges === 0 ? width : `calc(${width} + ${edges}rem)`
  })
}

/** The row that Tab reaches and the arrows move from: the selected trade's while it is drawn,
 * else the first drawn whole under the header row, so that a scrolled grid keeps one row in the
 * tab order. */
function tabbableRow(
  rows: readonly VirtualItem[],
  selected: number,
  scrolled: number | null
): number | null {
  if (rows.some((drawn) => drawn.index === selected)) {
    return selected
  }
  const top = (scrolled === null ? 0 : scrolled) + ROW_HEIGHT
  const inView = rows.find((drawn) => drawn.start >= top)
  return inView === undefined ? null : inView.index
}

function cellLook(figure: boolean): string {
  return cn(
    "h-10 overflow-hidden border-b px-2 text-ellipsis whitespace-pre first:pl-6 last:pr-6",
    figure ? "text-right" : "text-left"
  )
}

/** A column's header: its name in the tables' header type, and, where the server sorts by it, a
 * button that sorts the trades by it, the order shown by an arrow and to a screen reader. */
function GridHead({
  header,
}: Readonly<{ header: Header<typeof TRADE_TABLE_FEATURES, Trade, unknown> }>) {
  const column = tradeColumn(header.column.id)
  const sorted = header.column.getIsSorted()
  return (
    <th
      data-slot="table-head"
      scope="col"
      aria-sort={
        column.sort === null
          ? undefined
          : sorted === false
            ? "none"
            : ARIA_SORT[sorted]
      }
      className={cn(
        "h-10 border-b px-2 align-middle whitespace-nowrap first:pl-6 last:pr-6",
        column.figure ? "text-right" : "text-left"
      )}
    >
      {column.sort === null ? (
        column.label
      ) : (
        <button
          type="button"
          data-slot="sort-button"
          data-testid={`sort-${column.id}`}
          onClick={header.column.getToggleSortingHandler()}
          className="inline-flex items-center gap-1"
        >
          {column.label}
          {sorted === "asc" && (
            <ArrowUp className="size-3.5" aria-hidden="true" />
          )}
          {sorted === "desc" && (
            <ArrowDown className="size-3.5" aria-hidden="true" />
          )}
        </button>
      )}
    </th>
  )
}
