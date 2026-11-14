import { ChevronRight } from "lucide-react"
import type { components } from "@/api/schema"
import { formatCount } from "@/ui/figures"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"

type DatasetQuality = components["schemas"]["DatasetQuality"]

/** A quality report's findings behind a disclosure (web/DESIGN.md, Patterns, Disclosure row):
 * how many there are, then the first ones the API sends, each its trade date, kind, schema,
 * contract, and count; nothing where it found none. */
export function Findings({ quality }: Readonly<{ quality: DatasetQuality }>) {
  if (quality.findings_total === 0) {
    return null
  }
  const more = quality.findings_total - quality.findings.length
  const noun = quality.findings_total === 1 ? "finding" : "findings"
  return (
    <details className="group">
      <summary className="flex h-8 cursor-pointer list-none items-center gap-2 rounded-xl font-medium text-foreground">
        <ChevronRight className="size-4 transition-transform group-open:rotate-90" />
        {formatCount(quality.findings_total)} {noun}
      </summary>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="px-3 pl-0">Trade date</TableHead>
            <TableHead className="px-3">Kind</TableHead>
            <TableHead className="px-3">Data</TableHead>
            <TableHead className="px-3">Contract</TableHead>
            <TableHead className="px-3 pr-0 text-right">Count</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {quality.findings.map((finding, index) => (
            <TableRow key={index} className="h-10 hover:bg-transparent">
              <TableCell className="py-0 pr-3 pl-0">
                {finding.trade_date}
              </TableCell>
              <TableCell className="px-3 py-0">{finding.kind}</TableCell>
              <TableCell className="px-3 py-0">{finding.schema_name}</TableCell>
              <TableCell className="px-3 py-0">{finding.contract}</TableCell>
              <TableCell className="py-0 pr-0 pl-3 text-right">
                {formatCount(finding.count)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {more > 0 && (
        <p className="pt-2 text-foreground-secondary">
          And {formatCount(more)} more, in the report's findings.parquet.
        </p>
      )}
    </details>
  )
}
