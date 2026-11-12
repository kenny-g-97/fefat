import {
  type ChartOptions,
  ColorType,
  createChart,
  CrosshairMode,
  type DeepPartial,
  type IChartApi,
  type LogicalRange,
  type MouseEventParams,
  type Time,
  TickMarkType,
} from "lightweight-charts"
import {
  type KeyboardEvent,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react"
import type { ChartStyle } from "@/api/settings"
import { useShownTheme } from "@/ui/theme"
import { keyAction, type KeyAction } from "./chart-keys"
import { type ChartLook, chartLook, readThemeTokens } from "./chart-look"
import {
  barTime,
  crosshairTime,
  type TickMark,
  tickMarkLabel,
} from "./chart-time"
import {
  type ChartPane,
  type Drawn,
  drawPanes,
  type PriceFormat,
  restyle,
} from "./drawn-series"

/** How many bars lie before the view, and after it, in the first candle series. */
export type VisibleBars = Readonly<{ before: number; after: number }>

type PriceChartProps = Readonly<{
  label: string
  panes: readonly ChartPane[]
  style: ChartStyle
  priceFormat: PriceFormat
  wheel: "chart" | "page"
  onVisibleBarsChange?: (bars: VisibleBars) => void
  onCrosshairMove?: (index: number | null) => void
}>

const TICK_MARKS: Readonly<Record<TickMarkType, TickMark>> = {
  [TickMarkType.Year]: "year",
  [TickMarkType.Month]: "month",
  [TickMarkType.DayOfMonth]: "day",
  [TickMarkType.Time]: "time",
  [TickMarkType.TimeWithSeconds]: "seconds",
}

/** A price chart over Lightweight Charts 5 (`README.md`): its `panes` of candles and histograms
 * top to bottom, drawn in the trader's `style` in the theme the page shows, which a pane, a
 * series, or new bars change without drawing the chart anew; the wheel zooms it, or leaves the
 * page to scroll, and the keys pan and zoom it once focused. */
export function PriceChart({
  label,
  panes,
  style,
  priceFormat,
  wheel,
  onVisibleBarsChange,
  onCrosshairMove,
}: PriceChartProps) {
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<IChartApi | null>(null)
  const drawn = useRef(new Map<string, Drawn>())
  const [panesDrawn, setPanesDrawn] = useState(0)
  const theme = useShownTheme()
  const look = useMemo(
    () => chartLook(style, theme, readThemeTokens()),
    [style, theme]
  )

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
  const reportCrosshair = useEffectEvent((moved: MouseEventParams<Time>) => {
    const index =
      moved.point === undefined || moved.logical === undefined
        ? null
        : Math.round(moved.logical)
    onCrosshairMove?.(index)
  })
  const paint = useEffectEvent(() => {
    const current = chart.current
    if (current === null) {
      return
    }
    drawPanes(current, drawn.current, panes, look, priceFormat)
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
    created.subscribeCrosshairMove((moved) => reportCrosshair(moved))
    chart.current = created
    const kept = drawn.current
    return () => {
      created.remove()
      chart.current = null
      kept.clear()
    }
  }, [])

  useEffect(() => {
    chart.current?.applyOptions(lookOptions(look, wheel))
    restyle(drawn.current, look, priceFormat)
  }, [look, wheel, priceFormat])

  useEffect(() => paint(), [panes])

  const pressed = (event: KeyboardEvent<HTMLDivElement>) => {
    const action = keyAction(event.key)
    if (action === undefined || chart.current === null) {
      return
    }
    event.preventDefault()
    moved(chart.current, action)
  }

  return (
    <div
      role="application"
      aria-label={label}
      tabIndex={0}
      onKeyDown={pressed}
      data-slot="price-chart"
      data-testid="price-chart"
      data-panes={panesDrawn}
      className="relative min-h-0 min-w-0 flex-1 rounded-xl"
    >
      <div ref={host} className="absolute inset-0" />
    </div>
  )
}

function fixedOptions(): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      fontFamily: '"Geist Mono", ui-monospace, monospace',
      fontSize: 12,
      attributionLogo: true,
      panes: { enableResize: false },
    },
    localization: {
      timeFormatter: (time: Time) => crosshairTime(barTime(time)),
    },
    timeScale: {
      borderVisible: false,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time: Time, mark: TickMarkType) =>
        tickMarkLabel(barTime(time), TICK_MARKS[mark]),
    },
    rightPriceScale: { borderVisible: false, minimumWidth: 40 },
    grid: { vertLines: { visible: false } },
    crosshair: { mode: CrosshairMode.Normal },
  }
}

function lookOptions(
  look: ChartLook,
  wheel: "chart" | "page"
): DeepPartial<ChartOptions> {
  const line = {
    color: look.crosshair,
    labelBackgroundColor: look.crosshairLabel,
  }
  const wheeled = wheel === "chart"
  return {
    layout: {
      background: { type: ColorType.Solid, color: look.background },
      textColor: look.text,
      panes: { separatorColor: look.grid, separatorHoverColor: look.grid },
    },
    grid: { horzLines: { visible: look.gridShown, color: look.grid } },
    crosshair: { vertLine: line, horzLine: line },
    handleScroll: {
      mouseWheel: wheeled,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: false,
    },
    handleScale: {
      mouseWheel: wheeled,
      pinch: true,
      axisPressedMouseMove: true,
    },
  }
}

/** Pan, zoom, or go to the earliest or the latest bar loaded, as `action` asks. */
function moved(chart: IChartApi, action: KeyAction): void {
  const timeScale = chart.timeScale()
  if (action.kind === "latest") {
    timeScale.scrollToRealTime()
    return
  }
  if (action.kind === "zoom") {
    timeScale.applyOptions({
      barSpacing: timeScale.options().barSpacing * action.factor,
    })
    return
  }
  const range = timeScale.getVisibleLogicalRange()
  if (range === null) {
    return
  }
  const width = range.to - range.from
  const from =
    action.kind === "earliest" ? 0 : range.from + width * action.screens
  timeScale.setVisibleLogicalRange({ from, to: from + width })
}
