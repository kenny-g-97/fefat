import type { FileSeen } from "@/api/imports"
import { decimalsOf, formatAligned, formatCount } from "@/ui/figures"
import { formatInstant } from "@/ui/instant"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"

type FirstRecordsProps = Readonly<{ records: FileSeen["first_records"] }>

/** A file's first records as the store would hold them (web/DESIGN.md, Patterns, Review), a
 * table in the card: a bar's open and close in this browser's zone, its trade date and
 * contract, and its prices on their decimal points, or a print's arrival, price, size, and
 * side; the figures as the server gave them. */
export function FirstRecords({ records }: FirstRecordsProps) {
  if (records.rows.length === 0) {
    return null
  }
  return (
    <div className="flex flex-col gap-2" data-testid="first-records">
      <p className="font-medium text-foreground">First records as stored</p>
      <div className="-mx-6 overflow-x-auto">
        {records.kind === "bars" ? (
          <Bars rows={records.rows} />
        ) : (
          <Prints rows={records.rows} />
        )}
      </div>
    </div>
  )
}

type BarRows = Extract<FileSeen["first_records"], { kind: "bars" }>["rows"]
type PrintRows = Extract<FileSeen["first_records"], { kind: "prints" }>["rows"]

const CELL =
  "px-3 py-0 text-right whitespace-pre first:pl-6 first:text-left last:pr-6"

function Bars({ rows }: Readonly<{ rows: BarRows }>) {
  const places = Math.max(
    ...rows.flatMap((bar) =>
      [bar.open, bar.high, bar.low, bar.close].map(decimalsOf)
    )
  )
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {[
            "Open at",
            "Close at",
            "Trade date",
            "Contract",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
          ].map((name) => (
            <TableHead
              key={name}
              className="px-3 text-right first:pl-6 first:text-left last:pr-6"
            >
              {name}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((bar, at) => (
          <TableRow key={at} className="h-10 hover:bg-muted">
            <TableCell className={CELL}>{formatInstant(bar.ts_open)}</TableCell>
            <TableCell className={CELL}>
              {formatInstant(bar.ts_close)}
            </TableCell>
            <TableCell className={CELL}>{bar.trade_date}</TableCell>
            <TableCell className={CELL}>{bar.contract}</TableCell>
            {[bar.open, bar.high, bar.low, bar.close].map((price, index) => (
              <TableCell key={index} className={CELL}>
                {formatAligned(price, places)}
              </TableCell>
            ))}
            <TableCell className={CELL}>{formatCount(bar.volume)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Prints({ rows }: Readonly<{ rows: PrintRows }>) {
  const places = Math.max(...rows.map((print) => decimalsOf(print.price)))
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {["Received", "Trade date", "Contract", "Price", "Size", "Side"].map(
            (name) => (
              <TableHead
                key={name}
                className="px-3 text-right first:pl-6 first:text-left last:pr-6"
              >
                {name}
              </TableHead>
            )
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((print, at) => (
          <TableRow key={at} className="h-10 hover:bg-muted">
            <TableCell className={CELL}>{print.ts_recv}</TableCell>
            <TableCell className={CELL}>{print.trade_date}</TableCell>
            <TableCell className={CELL}>{print.contract}</TableCell>
            <TableCell className={CELL}>
              {formatAligned(print.price, places)}
            </TableCell>
            <TableCell className={CELL}>{formatCount(print.size)}</TableCell>
            <TableCell className={CELL}>{print.side}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
