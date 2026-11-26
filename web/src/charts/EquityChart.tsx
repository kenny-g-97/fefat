import { useCallback } from "react"
import type { BuyAndHoldCurve, EquityCurve } from "@/api/run-results"
import type { Currency } from "@/api/runs"
import type { ThemeTokens } from "./chart-look"
import { equityOption } from "./equity-option"
import { PointedChart } from "./PointedChart"

type EquityChartProps = Readonly<{
  label: string
  curve: EquityCurve
  buyAndHold: BuyAndHoldCurve | null
  currency: Currency
  pointed: number | null
  onPointed: (index: number | null) => void
}>

/** The equity curve over its drawdown (`README.md`), with buy and hold beside it where the run
 * has it: it fills the box it is in, its axes in `currency`, and tells `onPointed` the decision
 * under the pointer, or null once the pointer leaves it. Focused, the arrows step a decision, Home
 * and End go to either end, and Escape or leaving it gives the readout back to the last
 * (`PointedChart`). */
export function EquityChart({
  label,
  curve,
  buyAndHold,
  currency,
  pointed,
  onPointed,
}: EquityChartProps) {
  const optionIn = useCallback(
    (tokens: ThemeTokens) => equityOption(curve, currency, tokens, buyAndHold),
    [curve, currency, buyAndHold]
  )
  return (
    <PointedChart
      label={label}
      testId="equity-chart"
      optionIn={optionIn}
      last={curve.time.length - 1}
      pointed={pointed}
      onPointed={onPointed}
    />
  )
}
