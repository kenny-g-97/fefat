import { useCallback } from "react"
import type { EquityFan } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import type { ThemeTokens } from "./chart-look"
import { fanOption } from "./fan-option"
import { PointedChart } from "./PointedChart"

type FanChartProps = Readonly<{
  label: string
  fan: EquityFan
  currency: Currency
  pointed: number | null
  onPointed: (index: number | null) => void
}>

/** The paths' equity fan of a run's Monte Carlo (`README.md`): it fills the box it is in, its
 * value axis in `currency`, and tells `onPointed` the count of trades under the pointer, as its
 * index in the fan's columns, or null once the pointer leaves it; its keys are `PointedChart`'s. */
export function FanChart({
  label,
  fan,
  currency,
  pointed,
  onPointed,
}: FanChartProps) {
  const optionIn = useCallback(
    (tokens: ThemeTokens) => fanOption(fan, currency, tokens),
    [fan, currency]
  )
  return (
    <PointedChart
      label={label}
      testId="fan-chart"
      optionIn={optionIn}
      last={fan.trades_made.length - 1}
      pointed={pointed}
      onPointed={onPointed}
    />
  )
}
