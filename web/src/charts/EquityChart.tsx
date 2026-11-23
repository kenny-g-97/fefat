import { LineChart } from "echarts/charts"
import {
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components"
import { init, use as registerParts } from "echarts/core"
import { CanvasRenderer } from "echarts/renderers"
import { type KeyboardEvent, useEffect, useRef } from "react"
import { z } from "zod"
import type { EquityCurve } from "@/api/run-results"
import { useShownTheme } from "@/ui/theme"
import { readThemeTokens } from "./chart-look"
import { equityOption } from "./equity-option"

registerParts([
  LineChart,
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
])

/** What ECharts' `updateAxisPointer` event names of the decision under the pointer, which its
 * types leave open; none while the pointer stands on no decision. */
const pointerEvent = z.looseObject({ dataIndex: z.number().int().optional() })

type EquityChartProps = Readonly<{
  label: string
  curve: EquityCurve
  pointed: number | null
  onPointed: (index: number | null) => void
}>

/** The equity curve over its drawdown (`README.md`), over ECharts 6, which only this file and
 * `equity-option.ts` import: it fills the box it is in and tells `onPointed` the decision under
 * the pointer, or null when it leaves. Focused, the arrows step a decision, Home and End go to
 * either end, and Escape gives the readout back to the last. */
export function EquityChart({
  label,
  curve,
  pointed,
  onPointed,
}: EquityChartProps) {
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<ReturnType<typeof init>>(null)
  const theme = useShownTheme()

  useEffect(() => {
    if (host.current === null) {
      return
    }
    const drawn = init(host.current)
    chart.current = drawn
    drawn.on("updateAxisPointer", (event: unknown) => {
      const read = pointerEvent.safeParse(event)
      const decision = read.success ? read.data.dataIndex : undefined
      onPointed(decision === undefined ? null : decision)
    })
    drawn.on("globalout", () => onPointed(null))
    const sized = new ResizeObserver(() => drawn.resize())
    sized.observe(host.current)
    return () => {
      sized.disconnect()
      drawn.dispose()
      chart.current = null
    }
  }, [onPointed])

  useEffect(() => {
    chart.current?.setOption(equityOption(curve, readThemeTokens()), {
      notMerge: true,
    })
  }, [curve, theme])

  const pressed = (event: KeyboardEvent<HTMLDivElement>) => {
    const last = curve.time.length - 1
    if (event.key === "Escape") {
      chart.current?.dispatchAction({ type: "hideTip" })
      onPointed(null)
      return
    }
    const next = steppedTo(event.key, pointed === null ? last : pointed, last)
    if (next === null) {
      return
    }
    event.preventDefault()
    chart.current?.dispatchAction({
      type: "showTip",
      seriesIndex: 0,
      dataIndex: next,
    })
    onPointed(next)
  }

  return (
    <div
      role="application"
      aria-label={label}
      tabIndex={0}
      onKeyDown={pressed}
      data-testid="equity-chart"
      className="relative h-full min-w-0 rounded-xl"
    >
      <div ref={host} className="absolute inset-0" />
    </div>
  )
}

/** The decision a key leads to from `from`, none for a key the chart does not take. */
function steppedTo(key: string, from: number, last: number): number | null {
  if (key === "ArrowLeft") {
    return Math.max(from - 1, 0)
  }
  if (key === "ArrowRight") {
    return Math.min(from + 1, last)
  }
  if (key === "Home") {
    return 0
  }
  return key === "End" ? last : null
}
