import { lazyRouteComponent } from "@tanstack/react-router"
import { cn } from "cn"
import { Suspense, useState } from "react"
import type { ComparedRun } from "@/api/comparisons"
import { comparedDays, sharesOn } from "@/charts/comparison-option"
import { formatShare } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { Panel } from "@/ui/panel"
import { comparedDetail, comparedLabel, SERIES_MARKS } from "./compare-words"

/** ECharts' chunk, loaded with the first chart a page shows, out of the app's first bundle
 * (D-93), as the equity chart's is. */
const ComparisonChart = lazyRouteComponent(
  () => import("@/charts/ComparisonChart"),
  "ComparisonChart"
)

const KEY_DIGITS = 12

/** The compared runs' equity over their capital on one chart (web/DESIGN.md, Patterns,
 * Comparison chart): its readout is the legend, each run's share of its capital at the trade date
 * under the pointer, or else at the last, under that date. */
export function ComparisonEquityCard({
  runs,
}: Readonly<{ runs: readonly ComparedRun[] }>) {
  const [pointed, setPointed] = useState<number | null>(null)
  const curves = runs.map((run) => run.curve)
  const days = comparedDays(curves)
  const at = pointed === null ? days.length - 1 : pointed
  return (
    <Panel
      title="Equity"
      description="Each run's equity at each trade date's end, as a share of its capital"
    >
      {days.length === 0 ? (
        <p className="text-foreground-secondary">
          These runs valued their accounts on no trade date, so they have no
          curve.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <p
            data-testid="comparison-date"
            className="text-foreground-secondary"
          >
            {days[at]}
          </p>
          <ul data-testid="comparison-legend" className="flex flex-col gap-2">
            {runs.map((run, index) => (
              <li
                key={run.run_key}
                data-testid="comparison-legend-run"
                className="flex min-w-0 items-center gap-3"
              >
                <span
                  data-slot="chart-mark"
                  className={cn(
                    "size-2.5 shrink-0 rounded-xl",
                    SERIES_MARKS[index]
                  )}
                />
                <span className="font-medium whitespace-nowrap text-foreground">
                  {comparedLabel(run)}
                </span>
                <IdentityChip>{run.run_key.slice(0, KEY_DIGITS)}</IdentityChip>
                <span className="min-w-0 truncate text-xs text-muted-foreground">
                  {comparedDetail(run)}
                </span>
                <span
                  data-testid="comparison-share"
                  className="ml-auto font-semibold whitespace-nowrap text-foreground"
                >
                  {shareWords(sharesOn(days, run.curve)[at])}
                </span>
              </li>
            ))}
            <li className="flex items-center gap-3 text-xs text-foreground-secondary">
              <span className="w-2.5 shrink-0 border-t border-dashed border-foreground-secondary" />
              Capital, 100%
            </li>
          </ul>
          <div className="h-80">
            <Suspense fallback={<div className="h-full" />}>
              <ComparisonChart
                label={`Equity of ${runs.length} runs over their capital. The arrow keys step through the trade dates.`}
                curves={curves}
                pointed={pointed}
                onPointed={setPointed}
              />
            </Suspense>
          </div>
        </div>
      )}
    </Panel>
  )
}

/** A run's share of its capital at a trade date, None where it was not valued that day. */
function shareWords(share: number | null | undefined): string {
  return share === null || share === undefined ? "None" : formatShare(share)
}
