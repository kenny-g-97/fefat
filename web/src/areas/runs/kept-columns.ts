import { z } from "zod"
import { SHOWN_COLUMNS } from "./trade-columns"

/** Where this browser keeps the trade table's columns the trader showed and hid (web/DESIGN.md,
 * Patterns, Column chooser): a choice of how this trader reads a table, which suits every run. */
const KEPT_AS = "fefat_trade_columns"

const kept = z.record(z.string(), z.boolean())

/** The columns shown and hidden that `stored` keeps, for the columns the table still has, and
 * for the rest the table's own choice; the table's alone for nothing kept or text it cannot
 * read. */
export function columnsKeptIn(
  stored: string | null
): Readonly<Record<string, boolean>> {
  if (stored === null) {
    return SHOWN_COLUMNS
  }
  const read = kept.safeParse(parsed(stored))
  if (!read.success) {
    return SHOWN_COLUMNS
  }
  const known = Object.entries(read.data).filter(([id]) => id in SHOWN_COLUMNS)
  return { ...SHOWN_COLUMNS, ...Object.fromEntries(known) }
}

function parsed(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/** The columns this browser keeps (`columnsKeptIn`). */
export function keptColumns(): Readonly<Record<string, boolean>> {
  try {
    return columnsKeptIn(localStorage.getItem(KEPT_AS))
  } catch {
    // A browser that refuses its storage, as a private window may, keeps nothing.
    return SHOWN_COLUMNS
  }
}

/** Keep the columns shown and hidden for the next table this browser draws. */
export function keepColumns(
  visibility: Readonly<Record<string, boolean>>
): void {
  try {
    localStorage.setItem(KEPT_AS, JSON.stringify(visibility))
  } catch {
    // Storage refused or full: the choice holds while the page does.
  }
}
