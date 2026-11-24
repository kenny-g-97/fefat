import { cn } from "cn"
import type { Histogram } from "@/api/run-results"
import { counted, formatEdge } from "@/ui/figures"

/** How far from either end of the axis a zero keeps its label, clear of the ends' own. */
const ZERO_LABEL_MARGIN = 0.2

type HistogramChartProps = Readonly<{
  testId: string
  label: string
  note?: string
  bins: Histogram
  signed?: boolean
  edge?: (edge: number) => string
}>

/** A histogram of a run's trades (`README.md`), one bar a bin of the server's, drawn in the page
 * so that each names its range and its count to a pointer and to a screen reader: `signed` for a
 * measure either side of zero, its bins in the sign colours with a mark at zero, the others in
 * grey, each edge written by `edge`, with the decimals it holds where it is left out. A bin
 * holding a trade always shows, however tall the tallest. */
export function HistogramChart({
  testId,
  label,
  note,
  bins,
  signed = false,
  edge = formatEdge,
}: HistogramChartProps) {
  const tallest = Math.max(...bins.trades)
  const count = bins.trades.length
  const zero = signed ? bins.lower.indexOf(0) / count : 0
  return (
    <figure data-testid={testId} className="flex min-w-0 flex-col gap-2">
      <figcaption className="flex items-baseline justify-between gap-3">
        <span className="font-medium text-foreground">{label}</span>
        {note !== undefined && (
          <span className="text-xs text-muted-foreground">{note}</span>
        )}
      </figcaption>
      {count === 0 ? (
        <p className="flex h-28 items-center text-xs text-muted-foreground">
          No trade has this measure.
        </p>
      ) : (
        <>
          <div className="relative">
            <ol
              aria-label={label}
              className="flex h-28 items-end gap-px border-b"
            >
              {bins.trades.map((trades, at) => {
                const words = binWords(
                  edge(bins.lower[at]),
                  edge(bins.upper[at]),
                  trades
                )
                return (
                  <li
                    key={bins.lower[at]}
                    aria-label={words}
                    title={words}
                    className="flex h-full min-w-0 flex-1 items-end"
                  >
                    <span
                      data-slot="chart-mark"
                      className={cn(
                        "block w-full rounded-t-[2px]",
                        trades > 0 && "min-h-0.5",
                        !signed && "bg-input",
                        signed && bins.upper[at] <= 0 && "bg-negative",
                        signed && bins.upper[at] > 0 && "bg-positive"
                      )}
                      style={{ height: `${(trades / tallest) * 100}%` }}
                    />
                  </li>
                )
              })}
            </ol>
            {zero > 0 && (
              <span
                data-slot="chart-zero"
                data-testid="histogram-zero"
                className="absolute inset-y-0 w-px bg-foreground-secondary"
                style={{ left: `calc(${zero * 100}% + ${zero}px - 1px)` }}
              />
            )}
          </div>
          <p className="relative flex justify-between text-xs text-muted-foreground">
            <span>{edge(bins.lower[0])}</span>
            {zero >= ZERO_LABEL_MARGIN && zero <= 1 - ZERO_LABEL_MARGIN && (
              <span
                className="absolute -translate-x-1/2"
                style={{ left: `${zero * 100}%` }}
              >
                0
              </span>
            )}
            <span>{edge(bins.upper[count - 1])}</span>
          </p>
        </>
      )}
    </figure>
  )
}

/** What a bar says of its bin: `-$150 to -$140: 3 trades`. */
function binWords(lower: string, upper: string, trades: number): string {
  return `${lower} to ${upper}: ${counted(trades, "trade")}`
}
