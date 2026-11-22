import type { TablePreview } from "@/api/imports"
import { formatCount } from "@/ui/figures"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/ui/table"
import { Picker } from "@/ui/picker"
import { picked } from "@/ui/choices"
import { BAR_ROLES, ROLE_LABELS, type Role, TICK_ROLES } from "./import-roles"

/** What stands over each of a file's columns: its own name, before a profile reads it; the
 * role a listed profile gives it; or a select of its role, for a new profile. */
export type ColumnHeads =
  | Readonly<{ kind: "names" }>
  | Readonly<{ kind: "roles"; roles: readonly Role[] }>
  | Readonly<{
      kind: "selects"
      roles: readonly Role[]
      ticks: boolean
      onRole: (index: number, role: Role) => void
    }>

type RowsProps = Readonly<{ table: TablePreview; heads: ColumnHeads }>

/** The file's first rows as it reads them (web/DESIGN.md, Patterns, Column roles), as written,
 * the file's text and not yet figures: each column under its role, a listed profile's, or a
 * select of it for a new profile, one role a column, a bar's or a tick's by the profile's
 * timeframe; before a profile, under the file's own column names. */
export function Rows({ table, heads }: RowsProps) {
  return (
    <div className="flex flex-col gap-2" data-testid="import-rows">
      <p className="text-xs text-muted-foreground">
        {`The first ${formatCount(table.rows.length)} of ${formatCount(table.rows_total)} rows of ${table.file_name}`}
      </p>
      <div className="-mx-6 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {table.columns.map((column, index) => (
                <TableHead
                  key={column}
                  className="h-12 px-3 first:pl-6 last:pr-6"
                >
                  <Head heads={heads} column={column} index={index} />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {table.rows.map((row, at) => (
              <TableRow key={at} className="h-10 hover:bg-muted">
                {row.map((cell, index) => (
                  <TableCell
                    key={index}
                    className="px-3 py-0 whitespace-nowrap first:pl-6 last:pr-6"
                  >
                    {cell}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

type HeadProps = Readonly<{ heads: ColumnHeads; column: string; index: number }>

function Head({ heads, column, index }: HeadProps) {
  switch (heads.kind) {
    case "names":
      return column
    case "roles":
      return ROLE_LABELS[heads.roles[index] ?? "unused"]
    case "selects": {
      const options = (heads.ticks ? TICK_ROLES : BAR_ROLES).map((role) => ({
        value: role,
        label: ROLE_LABELS[role],
      }))
      return (
        <Picker
          id={`import-role-${index}`}
          label={`Role of column ${index + 1}, ${column}`}
          value={heads.roles[index] ?? "unused"}
          options={options}
          size="sm"
          className="w-32"
          onChange={(role) => heads.onRole(index, picked(options, role))}
        />
      )
    }
  }
}
