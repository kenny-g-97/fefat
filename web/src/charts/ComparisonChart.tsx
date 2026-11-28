import { useCallback } from "react"
import type { ShareCurve } from "@/api/comparisons"
import type { ThemeTokens } from "./chart-look"
import { comparedDays, comparisonOption } from "./comparison-option"
import { PointedChart } from "./PointedChart"

type ComparisonChartProps = Readonly<{
  label: string
  curves: readonly ShareCurve[]
  pointed: number | null
  onPointed: (index: number | null) => void
}>

/** Two to four runs' equity over their capital on one axis of trade dates (`README.md`): it fills
 * the box it is in and tells `onPointed` the trade date under the pointer, by its place among
 * every run's dates (`comparedDays`), or null once the pointer leaves it. Focused, the arrows step
 * a trade date, Home and End go to either end, and Escape or leaving it gives the readout back to
 * the last (`PointedChart`). */
export function ComparisonChart({
  label,
  curves,
  pointed,
  onPointed,
}: ComparisonChartProps) {
  const optionIn = useCallback(
    (tokens: ThemeTokens) => comparisonOption(curves, tokens),
    [curves]
  )
  return (
    <PointedChart
      label={label}
      testId="comparison-chart"
      optionIn={optionIn}
      last={comparedDays(curves).length - 1}
      pointed={pointed}
      onPointed={onPointed}
    />
  )
}
