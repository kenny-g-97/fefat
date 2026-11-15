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
import { Picker } from "../Picker"
import { BAR_ROLES, ROLE_LABELS, type Role, TICK_ROLES } from "./import-roles"

type RowsProps = Readonly<{
  table: TablePreview
  roles: readonly Role[] | null
  ticks: boolean
  onRole: (index: number, role: Role, shown: readonly Role[]) => void
}>

/** The file's first rows as it reads them (web/DESIGN.md, Patterns, Column roles): for a new
 * profile, each column under a select of its role, one role a column, a bar's or a tick's by
 * the profile's timeframe; for a listed one, under the file's own column names. */
export function Rows({ table, roles, ticks, onRole }: RowsProps) {
  const options = (ticks ? TICK_ROLES : BAR_ROLES).map((role) => ({
    value: role,
    label: ROLE_LABELS[role],
  }))
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
                  {roles === null ? (
                    column
                  ) : (
                    <Picker
                      id={`import-role-${index}`}
                      label={`Role of column ${index + 1}, ${column}`}
                      value={roles[index] ?? "unused"}
                      options={options}
                      size="sm"
                      className="w-32"
                      onChange={(role) => onRole(index, roleOf(role), roles)}
                    />
                  )}
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

function roleOf(value: string): Role {
  const role = [...BAR_ROLES, ...TICK_ROLES].find((each) => each === value)
  if (role === undefined) {
    throw new Error(`Expected a column's role, got ${JSON.stringify(value)}.`)
  }
  return role
}
