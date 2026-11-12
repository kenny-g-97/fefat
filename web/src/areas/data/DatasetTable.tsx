import type { StoredDataset } from "@/api/catalog"
import { formatCount } from "@/ui/figures"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import { fidelityLabel } from "./datasets"

const HEAD =
  "h-10 px-3 text-xs font-semibold tracking-[0.125rem] text-foreground-secondary uppercase"

type Covered = StoredDataset & Readonly<{ coverage?: "complete" | "partial" }>

/** A provider's datasets of a root (web/DESIGN.md, Patterns, Tables): what each holds, its
 * contracts, its first and last trade date, and for a catalog product whether it starts with the
 * product's history. */
export function DatasetTable({
  datasets,
}: Readonly<{ datasets: readonly Covered[] }>) {
  const product = datasets.some((dataset) => dataset.coverage !== undefined)
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className={`${HEAD} pl-0`}>Data</TableHead>
          <TableHead className={`${HEAD} text-right`}>Contracts</TableHead>
          <TableHead className={`${HEAD} text-right`}>
            First trade date
          </TableHead>
          <TableHead className={`${HEAD} text-right`}>
            Last trade date
          </TableHead>
          {product && <TableHead className={`${HEAD} pr-0`}>History</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {datasets.map((dataset) => (
          <TableRow
            key={dataset.id}
            data-testid="dataset-row"
            className="h-10 hover:bg-transparent"
          >
            <TableCell className="py-0 pr-3 pl-0 font-medium text-foreground">
              {fidelityLabel(dataset.fidelity)}
            </TableCell>
            <TableCell className="px-3 py-0 text-right text-foreground-secondary">
              {formatCount(dataset.contracts)}
            </TableCell>
            <TableCell className="px-3 py-0 text-right text-foreground-secondary">
              {dataset.first_trade_date}
            </TableCell>
            <TableCell className="px-3 py-0 text-right text-foreground-secondary">
              {dataset.last_trade_date}
            </TableCell>
            {product && (
              <TableCell className="py-0 pr-0 pl-3 text-foreground-secondary">
                {dataset.coverage === "complete" ? "Complete" : "Partial"}
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
