import { Link } from "@tanstack/react-router"
import { cn } from "cn"
import { ArrowRight } from "lucide-react"
import { Fragment } from "react"
import { IdentityChip } from "@/ui/identity-chip"
import type { DrawnRow } from "./imported-filters"
import { QualityBadge } from "./QualityBadge"

// shortcut: fixed tracks fit a root of 12 characters, a provider of 13, and a type of 11 on one
// line, longer ones wrap; content-sized tracks through subgrid once real stores outgrow them.
const COLUMNS =
  "grid grid-cols-[6.5rem_7rem_6rem_minmax(0,1fr)_5.5rem_5.5rem_5.5rem_1rem] items-center gap-x-4 border px-2"

/** The header over a list of imported rows, on the rows' own columns (web/DESIGN.md, Patterns,
 * Link rows). */
export function ImportedHead() {
  return (
    <div
      data-testid="imported-head"
      className={cn(COLUMNS, "h-10 border-transparent border-b-border")}
    >
      <span data-slot="list-head">Instrument</span>
      <span data-slot="list-head">Provider</span>
      <span data-slot="list-head">Type</span>
      <span data-slot="list-head">Data</span>
      <span data-slot="list-head" className="text-right">
        From
      </span>
      <span data-slot="list-head" className="text-right">
        To
      </span>
      <span data-slot="list-head">Quality</span>
    </div>
  )
}

/** An instrument's data from one provider as a row (web/DESIGN.md, Patterns, Link rows), which
 * opens its dataset's page: the words its filters read, drawn as they are, its instrument, its
 * provider, its type, the kinds of data it holds, its first and last trade date, and how its
 * quality stands. */
export function ImportedRow({ row }: Readonly<{ row: DrawnRow }>) {
  const words = "text-foreground-secondary"
  const figure = "text-right text-foreground-secondary"
  return (
    <Link
      to="/data/dataset"
      search={{ instrument: row.instrument, provider: row.provider }}
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
        {row.instrument}
      </span>
      <span>
        <IdentityChip testId="provider-chip">{row.provider}</IdentityChip>
      </span>
      <span data-testid="imported-type" className={words}>
        {row.type}
      </span>
      <span data-testid="imported-kinds" className={words}>
        <Kinds kinds={row.kinds} />
      </span>
      <span data-testid="imported-from" className={figure}>
        {row.from}
      </span>
      <span data-testid="imported-to" className={figure}>
        <span className="sr-only">to </span>
        {row.to}
      </span>
      <span>
        <QualityBadge standing={row.standing} />
      </span>
      <ArrowRight
        aria-hidden="true"
        className="size-4 text-foreground-secondary"
      />
    </Link>
  )
}

/** The kinds of data a row holds, in a line that breaks between two of them and never inside
 * one, where its column cannot hold them all. */
function Kinds({ kinds }: Readonly<{ kinds: readonly string[] }>) {
  return kinds.map((kind, index) => (
    <Fragment key={`${index} ${kind}`}>
      <span className="whitespace-nowrap">
        {index < kinds.length - 1 ? `${kind},` : kind}
      </span>
      {index < kinds.length - 1 && " "}
    </Fragment>
  ))
}
