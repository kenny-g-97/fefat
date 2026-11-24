import { LineChart } from "echarts/charts"
import {
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components"
import {
  type EChartsCoreOption,
  init,
  use as registerParts,
} from "echarts/core"
import { CanvasRenderer } from "echarts/renderers"
import { type KeyboardEvent, useEffect, useRef } from "react"
import { z } from "zod"
import { useShownTheme } from "@/ui/theme"
import { readThemeTokens, type ThemeTokens } from "./chart-look"

registerParts([
  LineChart,
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
])

/** What ECharts' `updateAxisPointer` event names of the entry under the pointer, which its types
 * leave open; none in the band between two panes, where the readout stays put. */
const pointerEvent = z.looseObject({ dataIndex: z.number().int().optional() })

type PointedChartProps = Readonly<{
  label: string
  testId: string
  optionIn: (tokens: ThemeTokens) => EChartsCoreOption
  last: number
  pointed: number | null
  onPointed: (index: number | null) => void
}>

/** A results chart whose readout follows its pointer and its keys (`README.md`), over ECharts 6,
 * which only this file imports beside the options' types: it fills the box it is in, draws
 * `optionIn` the theme the page shows, again when the theme changes, and tells `onPointed` the
 * entry under the pointer, or null once the pointer leaves it. Focused, the arrows step an entry,
 * Home and End go to the first and to `last`, and Escape or leaving it gives the readout back to
 * the last. */
export function PointedChart({
  label,
  testId,
  optionIn,
  last,
  pointed,
  onPointed,
}: PointedChartProps) {
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
      if (read.success && read.data.dataIndex !== undefined) {
        onPointed(read.data.dataIndex)
      }
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

  // A new `onPointed` makes a new chart above, which this draws again.
  useEffect(() => {
    chart.current?.setOption(optionIn(readThemeTokens()), { notMerge: true })
  }, [optionIn, theme, onPointed])

  const letGo = () => {
    chart.current?.dispatchAction({
      type: "updateAxisPointer",
      currTrigger: "leave",
    })
    onPointed(null)
  }

  const pressed = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) {
      return
    }
    if (event.key === "Escape") {
      letGo()
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
      onBlur={() => {
        // The window going away keeps the reading, for a trader comparing it elsewhere.
        if (document.hasFocus()) {
          letGo()
        }
      }}
      data-testid={testId}
      className="relative h-full min-w-0 rounded-xl"
    >
      <div ref={host} className="absolute inset-0" />
    </div>
  )
}

/** The entry a key leads to from `from`, none for a key the chart does not take. */
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
