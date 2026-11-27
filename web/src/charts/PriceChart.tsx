import {
  createChart,
  type IChartApi,
  type LogicalRange,
  type MouseEventParams,
  type Time,
} from "lightweight-charts"
import {
  type Ref,
  useEffect,
  useEffectEvent,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react"
import type { ChartStyle } from "@/api/settings"
import { useShownTheme } from "@/ui/theme"
import { chartHandle, keptView, type PriceChartHandle } from "./chart-handle"
import { chartLook, readThemeTokens } from "./chart-look"
import { fixedOptions, lookOptions } from "./chart-options"
import { useChartKeys } from "./chart-steps"
import {
  type ChartPane,
  type Drawn,
  drawPanes,
  type PriceFormat,
  restyle,
} from "./drawn-series"
import { ViewWatch, watched } from "./view-watch"

/** How many bars lie before the view, and after it, in the first candle series. */
export type VisibleBars = Readonly<{ before: number; after: number }>

type PriceChartProps = Readonly<{
  label: string
  panes: readonly ChartPane[]
  style: ChartStyle
  priceFormat: PriceFormat
  wheel: "chart" | "page"
  ref?: Ref<PriceChartHandle>
  onVisibleBarsChange?: (bars: VisibleBars) => void
  onCrosshairMove?: (index: number | null) => void
  onMarkerHover?: (id: string | null) => void
  onViewChange?: () => void
}>

/** A price chart over Lightweight Charts 5 (`README.md`): its `panes` of candles, histograms,
 * and lines top to bottom, drawn in the trader's `style` in the theme the page shows, which a
 * pane, a series, or new bars change without drawing the chart anew; the wheel zooms it, or
 * leaves the page to scroll, and the keys pan and zoom it once focused, Shift with the arrows
 * stepping the crosshair a bar at a time; its `ref` shows a span of bars and locates a price. */
export function PriceChart({
  label,
  panes,
  style,
  priceFormat,
  wheel,
  ref,
  onVisibleBarsChange,
  onCrosshairMove,
  onMarkerHover,
  onViewChange,
}: PriceChartProps) {
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<IChartApi | null>(null)
  const drawn = useRef(new Map<string, Drawn>())
  const watch = useRef<ViewWatch | null>(null)
  const [panesDrawn, setPanesDrawn] = useState(0)
  const theme = useShownTheme()
  const look = useMemo(
    () => chartLook(style, theme, readThemeTokens()),
    [style, theme]
  )
  useImperativeHandle(ref, () => chartHandle(chart, drawn), [])

  const reportVisibleBars = useEffectEvent((range: LogicalRange | null) => {
    const candles = [...drawn.current.values()].find(
      (each) => each.kind === "candles"
    )
    const bars =
      range === null || candles === undefined
        ? null
        : candles.api.barsInLogicalRange(range)
    onVisibleBarsChange?.(
      bars === null
        ? { before: 0, after: 0 }
        : { before: bars.barsBefore, after: bars.barsAfter }
    )
  })
  const keys = useChartKeys(chart, drawn, onCrosshairMove)
  const reportPointer = useEffectEvent((pointed: MouseEventParams<Time>) => {
    keys.pointed(
      pointed.point === undefined || pointed.logical === undefined
        ? null
        : Math.round(pointed.logical)
    )
    const hovered = pointed.hoveredObjectId
    onMarkerHover?.(
      typeof hovered === "string" && hovered !== "" ? hovered : null
    )
  })
  const reportView = useEffectEvent(() => onViewChange?.())
  const paint = useEffectEvent(() => {
    const current = chart.current
    const watching = watch.current
    if (current === null || watching === null) {
      return
    }
    const keep = keptView(current, drawn.current)
    drawPanes(
      current,
      drawn.current,
      watched(panes, watching),
      look,
      priceFormat
    )
    keep(drawn.current)
    setPanesDrawn(current.panes().length)
    reportVisibleBars(current.timeScale().getVisibleLogicalRange())
  })

  useEffect(() => {
    const element = host.current
    if (element === null) {
      return
    }
    const created = createChart(element, fixedOptions())
    created
      .timeScale()
      .subscribeVisibleLogicalRangeChange((range) => reportVisibleBars(range))
    created.subscribeCrosshairMove((pointed) => reportPointer(pointed))
    chart.current = created
    watch.current = new ViewWatch(() => reportView())
    const kept = drawn.current
    return () => {
      created.remove()
      chart.current = null
      watch.current = null
      kept.clear()
    }
  }, [])

  useEffect(() => {
    chart.current?.applyOptions(lookOptions(look, wheel))
    restyle(drawn.current, look, priceFormat)
  }, [look, wheel, priceFormat])

  useEffect(() => paint(), [panes])

  return (
    <div
      role="application"
      aria-label={label}
      tabIndex={0}
      onKeyDown={keys.pressed}
      onBlur={keys.left}
      data-slot="price-chart"
      data-testid="price-chart"
      data-panes={panesDrawn}
      className="relative min-h-0 min-w-0 flex-1 rounded-xl"
    >
      <div ref={host} className="absolute inset-0" />
    </div>
  )
}
