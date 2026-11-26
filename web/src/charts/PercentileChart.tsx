import { useCallback } from "react"
import type { FigureAtPercents } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import type { ThemeTokens } from "./chart-look"
import { percentileOption } from "./percentile-option"
import { PointedChart } from "./PointedChart"

type PercentileChartProps = Readonly<{
  label: string
  figure: FigureAtPercents
  currency: Currency | null
  rest: number
  pointed: number | null
  onPointed: (index: number | null) => void
}>

/** A figure of a run's Monte Carlo against the percent of its paths (`README.md`): it fills the
 * box it is in, its value axis in `currency`, or plain where none, and tells `onPointed` the
 * percent under the pointer or the keys, or null once the pointer leaves it; its keys are
 * `PointedChart`'s, stepping from `rest` while nothing is pointed at. */
export function PercentileChart({
  label,
  figure,
  currency,
  rest,
  pointed,
  onPointed,
}: PercentileChartProps) {
  const optionIn = useCallback(
    (tokens: ThemeTokens) => percentileOption(figure, currency, tokens),
    [figure, currency]
  )
  return (
    <PointedChart
      label={label}
      testId="percentile-chart"
      optionIn={optionIn}
      last={figure.at_percent.length - 1}
      rest={rest}
      pointed={pointed}
      onPointed={onPointed}
    />
  )
}
