import { cn } from "cn"
import { useRef, useState } from "react"
import { type QueryAnswer, useRunQuery } from "@/api/trades"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import { Label } from "@/ui/label"
import { Textarea } from "@/ui/textarea"
import {
  gridHeights,
  useScrolledSideways,
  useVirtualRows,
} from "./virtual-rows"

/** The query a SQL tab opens with: the trades as their table shows them, a page's worth. */
const FIRST_QUERY = "SELECT * FROM trades ORDER BY trade LIMIT 100"
/** DuckDB's types of whole numbers and decimals, whose cells align right; a list of them, an
 * interval, and every other type align left. */
const FIGURE_TYPE =
  /^(U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?|DOUBLE|FLOAT|REAL|DECIMAL(\(\d+,\s*\d+\))?)$/

/** The trade table's SQL tab (web/DESIGN.md, Patterns, SQL tab): one SELECT over the run's
 * artifacts, typed over its answer as the table's filters stand over their grid, run by Run
 * query or Ctrl+Enter, the server's refusal under it in its words, and the answer as a grid of
 * its own, counted. */
export function SqlTab({ runKey }: Readonly<{ runKey: string }>) {
  const query = useRunQuery(runKey)
  const [sql, setSql] = useState(FIRST_QUERY)
  const run = () => {
    if (!query.isPending) {
      query.mutate(sql)
    }
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          run()
        }}
      >
        <Label htmlFor="run-sql">SQL</Label>
        <Textarea
          id="run-sql"
          data-testid="run-sql"
          value={sql}
          spellCheck={false}
          aria-describedby="run-sql-tables"
          onChange={(event) => setSql(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault()
              run()
            }
          }}
        />
        <div className="flex items-start justify-between gap-4">
          <p id="run-sql-tables" className="text-xs text-muted-foreground">
            One SELECT over the run's artifacts, at most 10,000 rows: trades,
            fills, orders, log, costs, trade_paths, equity, equity_daily, and
            signals, prices and money in the instrument's units, instants in
            UTC. Ctrl+Enter runs the query.
          </p>
          <Button type="submit" disabled={query.isPending}>
            Run query
          </Button>
        </div>
        <p
          role="alert"
          data-testid="run-sql-refusal"
          className="min-w-0 text-negative wrap-anywhere"
        >
          {query.status === "error" ? query.error.message : ""}
        </p>
      </form>
      {query.status === "success" && <AnswerGrid answer={query.data} />}
    </div>
  )
}

/** A query's answer: how many rows, then its columns named as the query named them, over its
 * rows, only those near the view drawn. */
function AnswerGrid({ answer }: Readonly<{ answer: QueryAnswer }>) {
  const box = useRef<HTMLDivElement>(null)
  const { rows, above, below } = useVirtualRows(answer.rows.length, box)
  const sideways = useScrolledSideways(box)
  const figures = answer.columns.map((column) => FIGURE_TYPE.test(column.type))
  return (
    <section aria-label="Answer" className="flex min-h-0 flex-1 flex-col gap-3">
      <p
        role="status"
        data-testid="run-sql-count"
        className="text-foreground-secondary"
      >
        {counted(answer.rows.length, "row")}
      </p>
      <div
        ref={box}
        data-slot="data-grid"
        data-testid="run-sql-answer"
        data-sideways={sideways}
        style={gridHeights(answer.rows.length)}
        className="relative flex-[1_1_0px] overflow-auto rounded-xl border bg-card text-foreground-secondary shadow-raised"
      >
        <table
          role="grid"
          aria-label="Answer"
          aria-rowcount={answer.rows.length + 1}
          className="w-full border-separate border-spacing-0"
        >
          <thead data-slot="grid-head">
            <tr aria-rowindex={1}>
              {answer.columns.map((column, index) => (
                <th
                  key={`${column.name}-${index}`}
                  data-slot="table-head"
                  data-case="as-typed"
                  scope="col"
                  title={column.type}
                  className={cellLook(
                    figures[index],
                    "h-10 border-b px-2 align-middle"
                  )}
                >
                  {column.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {above > 0 && <tr aria-hidden="true" style={{ height: above }} />}
            {rows.map((drawn) => (
              <tr
                key={drawn.index}
                data-slot="grid-row"
                data-testid="run-sql-row"
                aria-rowindex={drawn.index + 2}
              >
                {(answer.rows.at(drawn.index) ?? []).map((value, index) => (
                  <td
                    key={index}
                    className={cellLook(figures[index], "h-10 border-b px-2")}
                  >
                    {value === null ? (
                      <span className="text-muted-foreground">NULL</span>
                    ) : (
                      cellText(value)
                    )}
                  </td>
                ))}
              </tr>
            ))}
            {below > 0 && <tr aria-hidden="true" style={{ height: below }} />}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function cellLook(figure: boolean | undefined, size: string): string {
  return cn(
    size,
    "whitespace-nowrap first:pl-6 last:pr-6",
    figure === true ? "text-right" : "text-left"
  )
}

/** A value of the answer as its cell shows it: text as it is, a number or a flag as JSON
 * writes it, a list or a record as JSON. */
function cellText(value: QueryAnswer["rows"][number][number]): string {
  return typeof value === "string" ? value : JSON.stringify(value)
}
