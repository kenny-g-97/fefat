import { cn } from "cn"
import type { MonthCoverage } from "@/api/catalog"
import { type MonthHeld, monthHeld, monthLabel } from "./datasets"

/** Each month's fill: the accent where every session holds records, half of it where some do,
 * the hover step where none does. */
const FILLS: Readonly<Record<MonthHeld, string>> = {
  every: "bg-brand",
  some: "bg-brand/40",
  none: "bg-accent",
}

/** A dataset's coverage by month (web/DESIGN.md, Patterns, Coverage strip): a cell a month of
 * its quality report, filled as `FILLS` says, a month with findings underlined in the negative
 * colour, each cell named in words for a screen reader and the pointer, with the first and the
 * last month under the strip. */
export function CoverageStrip({
  months,
}: Readonly<{ months: readonly MonthCoverage[] }>) {
  const first = months.at(0)
  const last = months.at(-1)
  if (first === undefined || last === undefined) {
    return null
  }
  return (
    <div className="flex flex-col gap-1">
      <ol aria-label="Coverage by month" className="flex h-4 gap-0.5">
        {months.map((month) => (
          <li
            key={month.month}
            data-testid="coverage-month"
            aria-label={monthLabel(month)}
            title={monthLabel(month)}
            className={cn(
              "min-w-0 flex-1 rounded-xl",
              FILLS[monthHeld(month)],
              month.findings > 0 && "border-b-2 border-negative"
            )}
          />
        ))}
      </ol>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{first.month}</span>
        <span>{last.month}</span>
      </div>
    </div>
  )
}

/** The strip's legend in words, under the panel's title: what each fill and the line mean. */
export function CoverageLegend() {
  const entries: readonly Readonly<{ fill: string; label: string }>[] = [
    { fill: FILLS.every, label: "Every session" },
    { fill: FILLS.some, label: "Some sessions" },
    { fill: FILLS.none, label: "No records" },
    { fill: "bg-negative", label: "Findings" },
  ]
  return (
    <ul
      aria-label="Coverage by month, the legend"
      className="flex shrink-0 flex-wrap items-center gap-4 text-xs text-foreground-secondary"
    >
      {entries.map(({ fill, label }) => (
        <li key={label} className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className={cn("size-2.5 rounded-xl", fill)}
          />
          {label}
        </li>
      ))}
    </ul>
  )
}
