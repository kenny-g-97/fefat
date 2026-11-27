import { Columns3 } from "lucide-react"
import { Button } from "@/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu"
import { SHOWN_COLUMNS, TRADE_COLUMNS } from "./trade-columns"

type ColumnChooserProps = Readonly<{
  visibility: Readonly<Record<string, boolean>>
  onChange: (visibility: Readonly<Record<string, boolean>>) => void
}>

/** The trade table's column chooser (web/DESIGN.md, Patterns, Column chooser): a menu of every
 * column but the entry's instant, which names a trade, each shown or hidden by a check that
 * leaves the menu open, so that several change at once, and the table's own columns again. */
export function ColumnChooser({ visibility, onChange }: ColumnChooserProps) {
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button data-slot="button" variant="ghost" data-testid="column-chooser">
          <Columns3 className="size-4" aria-hidden="true" />
          Columns
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" data-testid="column-menu">
        {TRADE_COLUMNS.filter((column) => column.id !== "entry_ts").map(
          (column) => (
            <DropdownMenuCheckboxItem
              key={column.id}
              checked={visibility[column.id]}
              onSelect={(event) => event.preventDefault()}
              onCheckedChange={(checked) =>
                onChange({ ...visibility, [column.id]: checked })
              }
            >
              {column.label}
            </DropdownMenuCheckboxItem>
          )
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem inset onSelect={() => onChange(SHOWN_COLUMNS)}>
          Show the table's own columns
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
