import { useQuery } from "@tanstack/react-query"
import { type InstrumentVersion, instrumentsQuery } from "@/api/catalog"
import { decimalsOf, formatAligned } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { Panel } from "@/ui/panel"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import { QueryBody } from "./QueryBody"

const KINDS: Readonly<Record<InstrumentVersion["kind"], string>> = {
  futures: "Futures",
  perpetual: "Perpetual",
  spot: "Spot",
}
const COLUMNS: readonly Readonly<{ label: string; numeric: boolean }>[] = [
  { label: "Instrument", numeric: false },
  { label: "Kind", numeric: false },
  { label: "Tick", numeric: true },
  { label: "Point value", numeric: true },
  { label: "Lot step", numeric: true },
  { label: "Currency", numeric: false },
  { label: "Calendar", numeric: false },
  { label: "In force", numeric: true },
]

/** An instrument's specification on its dataset's page (web/DESIGN.md, Patterns, Dataset page):
 * every version of it, FEAT's or the one an import saved, with the figures the API gives
 * written as their decimals, the tick and the point value a backtest's P&L is counted in. */
export function SpecificationPanel({ root }: Readonly<{ root: string }>) {
  const instruments = useQuery(instrumentsQuery)
  return (
    <Panel
      title="Specification"
      description="The instrument's specification by the dates it is in force, FEAT's or the one your import saved"
    >
      <QueryBody query={instruments}>
        {(versions) => (
          <Versions
            root={root}
            versions={versions.filter((version) => version.root === root)}
          />
        )}
      </QueryBody>
    </Panel>
  )
}

function Versions({
  root,
  versions,
}: Readonly<{ root: string; versions: readonly InstrumentVersion[] }>) {
  if (versions.length === 0) {
    return (
      <p className="text-foreground-secondary">
        FEAT holds no specification of {root}.
      </p>
    )
  }
  const places = placesOf(versions)
  return (
    <div className="-mx-6">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {COLUMNS.map(({ label, numeric }, index) => (
              <TableHead
                key={label}
                className={`px-3 ${numeric ? "text-right" : ""} ${index === 0 ? "pl-6" : ""} ${index === COLUMNS.length - 1 ? "pr-6" : ""}`}
              >
                {label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {versions.map((version) => (
            <VersionRow
              key={version.valid_from}
              version={version}
              places={places}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/** The decimals of each figure's column, so that its points line up (web/DESIGN.md, Type). */
type Places = Readonly<{ tick: number; point: number; lot: number }>

function placesOf(versions: readonly InstrumentVersion[]): Places {
  const most = (figure: (version: InstrumentVersion) => number) =>
    Math.max(0, ...versions.map((version) => decimalsOf(figure(version))))
  return {
    tick: most((version) => version.tick_size),
    point: most((version) => version.point_value),
    lot: most((version) => version.lot_step),
  }
}

function VersionRow({
  version,
  places,
}: Readonly<{ version: InstrumentVersion; places: Places }>) {
  const cell = "px-3 py-0 text-foreground-secondary"
  const figure = `${cell} text-right whitespace-pre`
  return (
    <TableRow className="h-10 hover:bg-muted">
      <TableCell className="py-0 pr-3 pl-6 font-medium text-foreground">
        <span className="flex items-center gap-2">
          {version.root}
          {version.saved && <IdentityChip>your import</IdentityChip>}
        </span>
      </TableCell>
      <TableCell className={cell}>{KINDS[version.kind]}</TableCell>
      <TableCell className={figure}>
        {formatAligned(version.tick_size, places.tick)}
      </TableCell>
      <TableCell className={figure}>
        {formatAligned(version.point_value, places.point)}
      </TableCell>
      <TableCell className={figure}>
        {formatAligned(version.lot_step, places.lot)}
      </TableCell>
      <TableCell className={cell}>{version.currency}</TableCell>
      <TableCell className={cell}>{version.calendar}</TableCell>
      <TableCell className={`${cell} pr-6 text-right`}>
        {version.valid_to === null
          ? `from ${version.valid_from}`
          : `${version.valid_from} until ${version.valid_to}`}
      </TableCell>
    </TableRow>
  )
}
