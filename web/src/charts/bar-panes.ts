import type { BarColumns, Timeframe } from "@/api/bar-windows"
import type { ChartTime } from "./chart-time"
import { rollMarks } from "./chart-marks"
import type { CandleSeries, ChartPane, HistogramSeries } from "./drawn-series"

/** The panes a price chart draws of `bars`: the candles, each roll of a spliced series marked
 * and every other session shaded, over the volume while the style shows it. A daily bar is
 * placed by its trade date and shades nothing, being a session of its own. The chart viewer's,
 * and the trade review's under its fills and its features (step 5.9). */
export function chartPanes(
  bars: BarColumns,
  timeframe: Timeframe,
  volumeShown: boolean
): readonly ChartPane[] {
  const daily = timeframe === "1d"
  const time: readonly ChartTime[] = daily ? bars.trade_date : bars.time
  const candles: CandleSeries = {
    kind: "candles",
    id: "price",
    time,
    open: bars.open,
    high: bars.high,
    low: bars.low,
    close: bars.close,
    ...(daily ? {} : { sessions: bars.trade_date }),
    markers: rollMarks(time, bars.contract),
  }
  const price: ChartPane = { id: "price", stretch: 4, series: [candles] }
  if (!volumeShown) {
    return [price]
  }
  const volume: HistogramSeries = {
    kind: "histogram",
    id: "volume",
    time,
    value: bars.volume,
    rising: bars.close.map((close, index) => close >= bars.open[index]),
  }
  return [price, { id: "volume", stretch: 1, series: [volume] }]
}
