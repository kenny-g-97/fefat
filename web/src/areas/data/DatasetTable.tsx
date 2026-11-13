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

type Covered = StoredDataset & Readonly<{ coverage?: "complete" | "partial" }>

/** A provider's datasets of a root, in their card (web/DESIGN.md, Patterns, Tables): what each
 * holds, its contracts, its first and last trade date, and for a catalog product whether it
 * starts with the product's history. */
export function DatasetTable({
  datasets,
}: Readonly<{ datasets: readonly Covered[] }>) {
  const product = datasets.some((dataset) => dataset.coverage !== undefined)
  const last = product ? "px-3" : "pr-6 pl-3"
  return (
    <div className="-mx-6">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pr-3 pl-6">Data</TableHead>
            <TableHead className="px-3 text-right">Contracts</TableHead>
            <TableHead className="px-3 text-right">First trade date</TableHead>
            <TableHead className={`${last} text-right`}>
              Last trade date
            </TableHead>
            {product && <TableHead className="pr-6 pl-3">History</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {datasets.map((dataset) => (
            <TableRow
              key={dataset.id}
              data-testid="dataset-row"
              className="h-10 hover:bg-muted"
            >
              <TableCell className="py-0 pr-3 pl-6 font-medium text-foreground">
                {fidelityLabel(dataset.fidelity)}
              </TableCell>
              <TableCell className="px-3 py-0 text-right text-foreground-secondary">
                {formatCount(dataset.contracts)}
              </TableCell>
              <TableCell className="px-3 py-0 text-right text-foreground-secondary">
                {dataset.first_trade_date}
              </TableCell>
              <TableCell
                className={`${last} py-0 text-right text-foreground-secondary`}
              >
                {dataset.last_trade_date}
              </TableCell>
              {product && (
                <TableCell className="py-0 pr-6 pl-3 text-foreground-secondary">
                  {dataset.coverage === "complete" ? "Complete" : "Partial"}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
