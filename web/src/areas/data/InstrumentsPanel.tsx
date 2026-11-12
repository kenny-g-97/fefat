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
  { label: "Root", numeric: false },
  { label: "Kind", numeric: false },
  { label: "Tick", numeric: true },
  { label: "Point value", numeric: true },
  { label: "Lot step", numeric: true },
  { label: "Currency", numeric: false },
  { label: "Calendar", numeric: false },
  { label: "In force", numeric: true },
]

/** Every version of every instrument's specification (web/DESIGN.md, Patterns, Tables), FEAT's
 * and those an import saved, with the figures the API gives written as their decimals. */
export function InstrumentsPanel() {
  const instruments = useQuery(instrumentsQuery)
  return (
    <Panel
      title="Instruments"
      description="Each instrument's specification, FEAT's and those your imports saved, by the dates it is in force"
    >
      <QueryBody query={instruments}>
        {(versions) => (
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
              <InstrumentRows versions={versions} />
            </Table>
          </div>
        )}
      </QueryBody>
    </Panel>
  )
}

function InstrumentRows({
  versions,
}: Readonly<{ versions: readonly InstrumentVersion[] }>) {
  const places = placesOf(versions)
  return (
    <TableBody>
      {versions.map((version) => (
        <InstrumentRow
          key={`${version.root} ${version.valid_from}`}
          version={version}
          places={places}
        />
      ))}
    </TableBody>
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

function InstrumentRow({
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
