import {
  columnVisibilityFeature,
  createColumnHelper,
  rowSortingFeature,
  tableFeatures,
} from "@tanstack/react-table"
import type { ReactNode } from "react"
import type { Currency } from "@/api/runs"
import type { Trade, TradeSort } from "@/api/trades"
import {
  alignedText,
  fidelityLabel,
  formatCount,
  formatDuration,
  formatFigure,
  formatMoney,
  moneySign,
  sentenceCase,
} from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { formatInstantToTheSecond } from "@/ui/instant"

/** The features of TanStack Table the trade table reads: its columns' sorting, which the server
 * does, and their visibility, which the column chooser sets. */
export const TRADE_TABLE_FEATURES = tableFeatures({
  rowSortingFeature,
  columnVisibilityFeature,
})

/** A column of decimals as the trades read so far write it: the most places any holds, at which
 * every point lines up, and the characters of the widest so written. */
export type DecimalColumn = Readonly<{ places: number; characters: number }>

/** What the trade table's cells read beyond their trade: the run's currency, and how each price
 * column lines its points up (`DecimalColumn`). */
export type TradeLook = Readonly<{
  currency: Currency | null
  entry: DecimalColumn
  exit: DecimalColumn
}>

/** A column of the trade table (web/DESIGN.md, Patterns, Trade table): the trade's field it
 * shows, its header, its width, or how it fits its widest cell with the look, whether it holds
 * figures, aligned right, whether it shows until hidden, how the server sorts by it, if it
 * does, and its cell. */
export type TradeColumn = Readonly<{
  id: string
  field: keyof Trade
  label: string
  width: string | ((look: TradeLook) => string)
  figure: boolean
  shown: boolean
  sort: Readonly<{ by: TradeSort; descFirst: boolean }> | null
  cell: (trade: Trade, look: TradeLook) => ReactNode
}>

const NONE = "None"

function money(text: string, look: TradeLook): ReactNode {
  return formatMoney(text, look.currency)
}

/** Money made or lost, in its sign's colour (web/DESIGN.md, Colour means something). */
function signed(text: string, look: TradeLook): ReactNode {
  const sign = moneySign(text)
  const tone =
    sign === "positive"
      ? "text-positive"
      : sign === "negative"
        ? "text-negative"
        : undefined
  return <span className={tone}>{formatMoney(text, look.currency)}</span>
}

function ratio(value: number | null): ReactNode {
  return value === null ? NONE : formatFigure(value)
}

function chip(contract: string): ReactNode {
  return <IdentityChip>{contract}</IdentityChip>
}

/** The width of a price column: 8 rem, or its widest text and the cell's padding where wider,
 * each monospaced figure a `ch`. */
function fitted(column: DecimalColumn): string {
  return `max(8rem, calc(${column.characters}ch + 1rem))`
}

/** Every column the trade table can show, in the order it shows them: the step's own first,
 * shown until hidden, then the rest of the trade's columns, hidden until shown. */
export const TRADE_COLUMNS: readonly TradeColumn[] = [
  {
    id: "entry_ts",
    field: "entry_ts",
    label: "Entry",
    width: "11.5rem",
    figure: true,
    shown: true,
    sort: { by: "entry_ts", descFirst: false },
    cell: (trade) => (
      <span className="text-foreground">
        {formatInstantToTheSecond(trade.entry_ts)}
      </span>
    ),
  },
  {
    id: "entry_price",
    field: "entry_price",
    label: "Entry price",
    width: (look) => fitted(look.entry),
    figure: true,
    shown: true,
    sort: null,
    cell: (trade, look) => alignedText(trade.entry_price, look.entry.places),
  },
  {
    id: "exit_ts",
    field: "exit_ts",
    label: "Exit",
    width: "11.5rem",
    figure: true,
    shown: true,
    sort: { by: "exit_ts", descFirst: false },
    cell: (trade) => formatInstantToTheSecond(trade.exit_ts),
  },
  {
    id: "exit_price",
    field: "exit_price",
    label: "Exit price",
    width: (look) => fitted(look.exit),
    figure: true,
    shown: true,
    sort: null,
    cell: (trade, look) =>
      trade.exit_price === null
        ? NONE
        : alignedText(trade.exit_price, look.exit.places),
  },
  {
    id: "side",
    field: "side",
    label: "Side",
    width: "5rem",
    figure: false,
    shown: true,
    sort: null,
    cell: (trade) => sentenceCase(trade.side),
  },
  {
    id: "lots",
    field: "lots",
    label: "Lots",
    width: "4.5rem",
    figure: true,
    shown: true,
    sort: null,
    cell: (trade) => formatCount(trade.lots),
  },
  {
    id: "pnl",
    field: "pnl",
    label: "Net P&L",
    width: "8.5rem",
    figure: true,
    shown: true,
    sort: { by: "pnl", descFirst: true },
    cell: (trade, look) => signed(trade.pnl, look),
  },
  {
    id: "r_multiple",
    field: "r_multiple",
    label: "R",
    width: "5rem",
    figure: true,
    shown: true,
    sort: { by: "r_multiple", descFirst: true },
    cell: (trade) => ratio(trade.r_multiple),
  },
  {
    id: "held",
    field: "held_minutes",
    label: "Held",
    width: "calc(19ch + 1rem)",
    figure: true,
    shown: true,
    sort: { by: "held", descFirst: true },
    cell: (trade) => formatDuration(trade.held_minutes),
  },
  {
    id: "mae_ticks",
    field: "mae_ticks",
    label: "MAE ticks",
    width: "7.5rem",
    figure: true,
    shown: true,
    sort: { by: "mae_ticks", descFirst: true },
    cell: (trade) => formatCount(trade.mae_ticks),
  },
  {
    id: "mfe_ticks",
    field: "mfe_ticks",
    label: "MFE ticks",
    width: "7.5rem",
    figure: true,
    shown: true,
    sort: { by: "mfe_ticks", descFirst: true },
    cell: (trade) => formatCount(trade.mfe_ticks),
  },
  {
    id: "exit_reason",
    field: "exit_reason",
    label: "Exit reason",
    width: "calc(18ch + 1rem)",
    figure: false,
    shown: true,
    sort: null,
    cell: (trade) => sentenceCase(trade.exit_reason),
  },
  {
    id: "entry_contract",
    field: "entry_contract",
    label: "Contract",
    width: "7.5rem",
    figure: false,
    shown: true,
    sort: null,
    cell: (trade) => chip(trade.entry_contract),
  },
  {
    id: "fidelity",
    field: "fidelity",
    label: "Fidelity",
    width: "9.5rem",
    figure: false,
    shown: true,
    sort: null,
    cell: (trade) => fidelityLabel(trade.fidelity),
  },
  {
    id: "ambiguous",
    field: "ambiguous",
    label: "Ambiguous",
    width: "7rem",
    figure: false,
    shown: true,
    sort: null,
    cell: (trade) => (trade.ambiguous ? "Yes" : "No"),
  },
  {
    id: "trade",
    field: "trade",
    label: "Row",
    width: "5rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => String(trade.trade),
  },
  {
    id: "entry_order",
    field: "entry_order",
    label: "Entry order",
    width: "8rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => String(trade.entry_order),
  },
  {
    id: "entry_trade_date",
    field: "entry_trade_date",
    label: "Trade date",
    width: "8rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => trade.entry_trade_date,
  },
  {
    id: "entry_decision",
    field: "entry_decision",
    label: "Decision",
    width: "11.5rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => formatInstantToTheSecond(trade.entry_decision),
  },
  {
    id: "exit_contract",
    field: "exit_contract",
    label: "Exit contract",
    width: "9rem",
    figure: false,
    shown: false,
    sort: null,
    cell: (trade) => chip(trade.exit_contract),
  },
  {
    id: "exits",
    field: "exits",
    label: "Exits",
    width: "5rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => formatCount(trade.exits),
  },
  {
    id: "rolls",
    field: "rolls",
    label: "Rolls",
    width: "5rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => formatCount(trade.rolls),
  },
  {
    id: "gross_pnl",
    field: "gross_pnl",
    label: "Gross P&L",
    width: "8.5rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade, look) => signed(trade.gross_pnl, look),
  },
  {
    id: "fees",
    field: "fees",
    label: "Fees",
    width: "7rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade, look) => money(trade.fees, look),
  },
  {
    id: "funding",
    field: "funding",
    label: "Funding",
    width: "7rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade, look) => money(trade.funding, look),
  },
  {
    id: "initial_risk_ticks",
    field: "initial_risk_ticks",
    label: "Risk ticks",
    width: "7rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) =>
      trade.initial_risk_ticks === null
        ? NONE
        : formatCount(trade.initial_risk_ticks),
  },
  {
    id: "initial_risk",
    field: "initial_risk",
    label: "Risk",
    width: "8rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade, look) =>
      trade.initial_risk === null ? NONE : money(trade.initial_risk, look),
  },
  {
    id: "mae",
    field: "mae",
    label: "MAE",
    width: "8rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade, look) => money(trade.mae, look),
  },
  {
    id: "mfe",
    field: "mfe",
    label: "MFE",
    width: "8rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade, look) => money(trade.mfe, look),
  },
  {
    id: "mae_r",
    field: "mae_r",
    label: "MAE R",
    width: "6rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => ratio(trade.mae_r),
  },
  {
    id: "mfe_r",
    field: "mfe_r",
    label: "MFE R",
    width: "6rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => ratio(trade.mfe_r),
  },
  {
    id: "max_drawdown_ticks",
    field: "max_drawdown_ticks",
    label: "Drawdown ticks",
    width: "9rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade) => formatCount(trade.max_drawdown_ticks),
  },
  {
    id: "max_drawdown",
    field: "max_drawdown",
    label: "Drawdown",
    width: "8rem",
    figure: true,
    shown: false,
    sort: null,
    cell: (trade, look) => money(trade.max_drawdown, look),
  },
  {
    id: "path_fidelity",
    field: "path_fidelity",
    label: "Path fidelity",
    width: "9.5rem",
    figure: false,
    shown: false,
    sort: null,
    cell: (trade) => fidelityLabel(trade.path_fidelity),
  },
]

const COLUMNS_BY_ID = new Map(
  TRADE_COLUMNS.map((column) => [column.id, column])
)

/** The column `id` names, which the trade table's definitions hold. */
export function tradeColumn(id: string): TradeColumn {
  const found = COLUMNS_BY_ID.get(id)
  if (found === undefined) {
    throw new Error(
      `Expected a column of the trade table, got ${JSON.stringify(id)}.`
    )
  }
  return found
}

/** The width the column `column` takes with `look`. */
export function columnWidth(column: TradeColumn, look: TradeLook): string {
  return typeof column.width === "string" ? column.width : column.width(look)
}

const columnBuilder = createColumnHelper<typeof TRADE_TABLE_FEATURES, Trade>()

/** The trade table's columns as TanStack Table defines them: each reads its trade's field, the
 * server sorting by those that sort, and draws its cell with `look`; the entry's instant, which
 * names a trade, never hides. */
export function tableColumns(look: TradeLook) {
  return columnBuilder.columns(
    TRADE_COLUMNS.map((column) =>
      columnBuilder.accessor((trade) => trade[column.field], {
        id: column.id,
        header: column.label,
        cell: (context) => column.cell(context.row.original, look),
        enableSorting: column.sort !== null,
        sortDescFirst: column.sort === null ? false : column.sort.descFirst,
        enableHiding: column.id !== "entry_ts",
      })
    )
  )
}

/** Which columns show until the trader chooses otherwise. */
export const SHOWN_COLUMNS: Readonly<Record<string, boolean>> =
  Object.fromEntries(TRADE_COLUMNS.map((column) => [column.id, column.shown]))
