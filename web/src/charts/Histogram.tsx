import { cn } from "cn"
import type { Histogram } from "@/api/run-results"
import { counted, formatEdge } from "@/ui/figures"

type HistogramChartProps = Readonly<{
  testId: string
  label: string
  note?: string
  bins: Histogram
  signed?: boolean
}>

/** A histogram of a run's trades (`README.md`), one bar a bin of the server's, drawn in the page
 * so that each names its range and its count to a pointer and to a screen reader: `signed` for a
 * measure either side of zero, its bins in the sign colours, the others in grey. */
export function HistogramChart({
  testId,
  label,
  note,
  bins,
  signed = false,
}: HistogramChartProps) {
  const tallest = Math.max(...bins.trades)
  const last = bins.trades.length - 1
  return (
    <figure data-testid={testId} className="flex min-w-0 flex-col gap-2">
      <figcaption className="flex items-baseline justify-between gap-3">
        <span className="font-medium text-foreground">{label}</span>
        {note !== undefined && (
          <span className="text-xs text-muted-foreground">{note}</span>
        )}
      </figcaption>
      {last < 0 ? (
        <p className="flex h-28 items-center text-xs text-muted-foreground">
          No trade has this measure.
        </p>
      ) : (
        <ol aria-label={label} className="flex h-28 items-end gap-px border-b">
          {bins.trades.map((count, at) => {
            const words = binWords(bins.lower[at], bins.upper[at], count)
            return (
              <li
                key={bins.lower[at]}
                aria-label={words}
                title={words}
                className="flex h-full min-w-0 flex-1 items-end"
              >
                <span
                  className={cn(
                    "block w-full rounded-t-[2px]",
                    !signed && "bg-input",
                    signed && bins.upper[at] <= 0 && "bg-negative",
                    signed && bins.upper[at] > 0 && "bg-positive"
                  )}
                  style={{ height: `${(count / tallest) * 100}%` }}
                />
              </li>
            )
          })}
        </ol>
      )}
      {last >= 0 && (
        <p className="flex justify-between text-xs text-muted-foreground">
          <span>{formatEdge(bins.lower[0])}</span>
          <span>{formatEdge(bins.upper[last])}</span>
        </p>
      )}
    </figure>
  )
}

/** What a bar says of its bin: `-150 to -140: 3 trades`. */
function binWords(lower: number, upper: number, count: number): string {
  return `${formatEdge(lower)} to ${formatEdge(upper)}: ${counted(count, "trade")}`
}
