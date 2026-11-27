import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react"
import type { ChartWindow } from "@/api/run-chart"
import type { ChartStyle } from "@/api/settings"
import type { Trade } from "@/api/trades"
import type { PriceChartHandle } from "@/charts/chart-handle"
import { chartLook, readThemeTokens } from "@/charts/chart-look"
import { ChartReadout } from "@/charts/ChartReadout"
import { PriceChart, type VisibleBars } from "@/charts/PriceChart"
import { TradeOverlay } from "@/charts/trade-overlay"
import { ChartFrame } from "@/ui/chart-frame"
import { decimalsOf } from "@/ui/figures"
import { usePageScrolls } from "@/ui/page-scroll"
import { useShownTheme } from "@/ui/theme"
import { MarkerTooltip, type TooltipPlace } from "./MarkerTooltip"
import { TRADE_CHART_FRAME } from "./trade-chart-frame"
import {
  barPlaces,
  drawnFills,
  entryBar,
  featureFields,
  fillId,
  overlayView,
  tooltipFill,
  tradePanes,
} from "./trade-panes"

type TradeChartViewProps = Readonly<{
  chart: ChartWindow
  timeframe: string
  style: ChartStyle
  selected: Trade | null
  loading: boolean
  onVisibleBarsChange: (bars: VisibleBars) => void
  attributes: Readonly<Record<`data-${string}`, string>>
}>

/** The trade review chart once a window is read: the readout of the bar under the crosshair with
 * the strategy's features there, the candles with every fill at its price, the trades'
 * connectors, the selected trade's bands, the volume, and a pane a feature; it shows the
 * selected trade's bars once per selection, and a tooltip names a fill (`tooltipFill`). */
export function TradeChartView({
  chart,
  timeframe,
  style,
  selected,
  loading,
  onVisibleBarsChange,
  attributes,
}: TradeChartViewProps) {
  const handle = useRef<PriceChartHandle>(null)
  const box = useRef<HTMLDivElement>(null)
  const [overlay] = useState(() => new TradeOverlay())
  const [crosshair, setCrosshair] = useState<number | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [place, setPlace] = useState<TooltipPlace | null>(null)
  const [centredOn, setCentredOn] = useState<number | null>(null)
  const theme = useShownTheme()
  const scrolls = usePageScrolls()
  const daily = timeframe === "1d"
  const row = selected === null ? null : selected.trade
  const tick = Number(chart.tickSize)
  const priceFormat = useMemo(
    () => ({ precision: decimalsOf(tick), minMove: tick }),
    [tick]
  )
  const places = useMemo(
    () => barPlaces(chart.bars, daily),
    [chart.bars, daily]
  )
  const fills = useMemo(() => drawnFills(chart, places), [chart, places])
  const panes = useMemo(
    () =>
      tradePanes(chart, timeframe, style.volume_shown, fills, {
        selected: row,
        overlay,
      }),
    [chart, timeframe, style.volume_shown, fills, row, overlay]
  )
  const colours = useMemo(
    () => chartLook(style, theme, readThemeTokens()).markers,
    [style, theme]
  )
  const tooltip = useMemo(
    () => tooltipFill(chart, fills, row, { hovered, crosshair }),
    [chart, fills, row, hovered, crosshair]
  )
  const placeTooltip = () => {
    const located =
      tooltip === null || handle.current === null
        ? null
        : handle.current.locate(tooltip.drawn.time, tooltip.drawn.price)
    const frame = box.current
    setPlace(
      located === null || frame === null
        ? null
        : { ...located, width: frame.clientWidth, height: frame.clientHeight }
    )
  }
  const placeOnChange = useEffectEvent(placeTooltip)
  const centre = useEffectEvent(() => {
    const trade = chart.trades.find((each) => each.trade === row)
    const entry = trade === undefined ? undefined : fills.get(fillId(trade, 0))
    if (trade === undefined || entry === undefined || handle.current === null) {
      return
    }
    const exit = fills.get(fillId(trade, trade.fills.length - 1))
    const last = exit === undefined ? entry.time : exit.time
    if (centredOn !== row && handle.current.showBars(entry.time, last)) {
      setCentredOn(row)
    }
  })
  useEffect(() => {
    overlay.show(overlayView(chart, fills, row, colours))
  }, [overlay, chart, fills, row, colours])
  useEffect(() => centre(), [fills, row])
  useEffect(() => placeOnChange(), [tooltip, panes])
  return (
    <ChartFrame
      {...TRADE_CHART_FRAME}
      loading={loading}
      attributes={{
        ...attributes,
        "data-bars": String(chart.bars.time.length),
        "data-centred-on": centredOn === null ? "" : String(centredOn),
      }}
    >
      <ChartReadout
        bars={chart.bars}
        index={crosshair === null ? entryBar(chart, fills, row) : crosshair}
        decimals={priceFormat.precision}
        daily={daily}
        loading={loading}
        extra={featureFields(chart)}
      />
      <div ref={box} className="relative flex min-h-0 flex-1 flex-col">
        <PriceChart
          ref={handle}
          label={`The run's ${timeframe} bars with its fills`}
          panes={panes}
          style={style}
          priceFormat={priceFormat}
          wheel={scrolls ? "page" : "chart"}
          keepsBarsOnResize
          onVisibleBarsChange={onVisibleBarsChange}
          onCrosshairMove={setCrosshair}
          onMarkerHover={setHovered}
          onViewChange={placeTooltip}
        />
        {tooltip !== null && place !== null && (
          <MarkerTooltip
            drawn={tooltip.drawn}
            place={place}
            pinned={tooltip.pinned}
          />
        )}
      </div>
    </ChartFrame>
  )
}
