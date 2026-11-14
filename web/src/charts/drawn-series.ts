import {
  CandlestickSeries,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ISeriesPrimitive,
  LineStyle,
  type SeriesMarker,
  type Time,
} from "lightweight-charts"
import { type ChartLook, lastBarColour, legibleText } from "./chart-look"
import { type ChartMarker, type SessionSpan, sessionSpans } from "./chart-marks"
import { type ChartTime, chartTime } from "./chart-time"
import { SessionShading } from "./session-shading"

/** A candle series: its bars column by column, as the API sends them, with the trade date of
 * each bar for the sessions' shading, its markers, and primitives of the caller's own. */
export type CandleSeries = Readonly<{
  kind: "candles"
  id: string
  time: readonly ChartTime[]
  open: readonly number[]
  high: readonly number[]
  low: readonly number[]
  close: readonly number[]
  sessions?: readonly string[]
  markers?: readonly ChartMarker[]
  primitives?: readonly ISeriesPrimitive<Time>[]
}>

/** A histogram series, such as volume, each bar rising or not where it takes its candle's
 * colour. */
export type HistogramSeries = Readonly<{
  kind: "histogram"
  id: string
  time: readonly ChartTime[]
  value: readonly number[]
  rising?: readonly boolean[]
}>

export type ChartSeries = CandleSeries | HistogramSeries

/** A pane of the chart, top to bottom, its share of the height, and its series. */
export type ChartPane = Readonly<{
  id: string
  stretch: number
  series: readonly ChartSeries[]
}>

/** How the price axis writes a price: its decimals and its tick. */
export type PriceFormat = Readonly<{ precision: number; minMove: number }>

type DrawnCandles = {
  kind: "candles"
  api: ISeriesApi<"Candlestick">
  lastPrice: IPriceLine
  markers: ISeriesMarkersPluginApi<Time>
  shading: SessionShading
  spans: readonly SessionSpan[]
  primitives: readonly ISeriesPrimitive<Time>[]
  last: CandleSeries
}

type DrawnHistogram = {
  kind: "histogram"
  api: ISeriesApi<"Histogram">
  byDirection: boolean
  last: HistogramSeries
}

/** A series the chart draws, with what it last drew. */
export type Drawn = DrawnCandles | DrawnHistogram

type Wanted = Readonly<{ series: ChartSeries; pane: number }>

/** Draw `panes` on `chart`: remove the series `drawn` holds that `panes` lacks or draws as
 * another kind, and every series where one is left out of its pane, add those it lacks in pane
 * order, a pane made for each new one, and give each its bars, markers, shading, and primitives
 * in `look`. */
export function drawPanes(
  chart: IChartApi,
  drawn: Map<string, Drawn>,
  panes: readonly ChartPane[],
  look: ChartLook,
  format: PriceFormat
): void {
  const wanted = new Map<string, Wanted>(
    panes.flatMap((pane, index) =>
      pane.series.map((series): [string, Wanted] => [
        series.id,
        { series, pane: index },
      ])
    )
  )
  for (const [id, each] of [...drawn]) {
    const want = wanted.get(id)
    if (want === undefined || want.series.kind !== each.kind) {
      chart.removeSeries(each.api)
      drawn.delete(id)
    }
  }
  // The library removes a pane with its last series and moves the panes below it up.
  const misplaced = [...drawn].some(
    ([id, each]) => wanted.get(id)?.pane !== each.api.getPane().paneIndex()
  )
  if (misplaced) {
    drawn.forEach((each) => chart.removeSeries(each.api))
    drawn.clear()
  }
  panes.forEach((pane, index) => {
    for (const series of pane.series) {
      const kept = drawn.get(series.id)
      const each = kept === undefined ? added(chart, series, index) : kept
      drawn.set(series.id, painted(each, series, { look, format, bars: true }))
    }
    chart.panes()[index]?.setStretchFactor(pane.stretch)
  })
}

/** Give every series `drawn` holds the colours of `look` and the price format `format`, its bars
 * kept but where a bar's own colour follows the look, as volume's by direction does. */
export function restyle(
  drawn: Map<string, Drawn>,
  look: ChartLook,
  format: PriceFormat
): void {
  for (const [id, each] of drawn) {
    drawn.set(id, painted(each, each.last, { look, format, bars: false }))
  }
}

/** How a series is painted: in `look`, its prices written in `format`, and its bars set anew
 * where `bars` is true. */
type Painting = Readonly<{
  look: ChartLook
  format: PriceFormat
  bars: boolean
}>

function added(chart: IChartApi, series: ChartSeries, pane: number): Drawn {
  // The readout gives the volume, and the candles' last price is a line of the chart's own,
  // which the library's would leave for the last bar in view as the trader scrolls back.
  const unlabelled = { lastValueVisible: false, priceLineVisible: false }
  if (series.kind === "histogram") {
    const api = chart.addSeries(
      HistogramSeries,
      { ...unlabelled, priceFormat: { type: "volume" } },
      pane
    )
    return { kind: "histogram", api, byDirection: false, last: series }
  }
  const api = chart.addSeries(CandlestickSeries, unlabelled, pane)
  const lastPrice = api.createPriceLine({
    price: 0,
    lineStyle: LineStyle.Dashed,
    lineVisible: false,
    axisLabelVisible: false,
  })
  const shading = new SessionShading()
  api.attachPrimitive(shading)
  const markers = createSeriesMarkers(api, [])
  return {
    kind: "candles",
    api,
    lastPrice,
    markers,
    shading,
    spans: [],
    primitives: [],
    last: series,
  }
}

function painted(each: Drawn, series: ChartSeries, painting: Painting): Drawn {
  if (each.kind === "candles" && series.kind === "candles") {
    return paintedCandles(each, series, painting)
  }
  if (each.kind === "histogram" && series.kind === "histogram") {
    return paintedHistogram(each, series, painting)
  }
  throw new Error(
    `Expected the series ${series.id} drawn as ${series.kind}, got ${each.kind}.`
  )
}

function paintedCandles(
  each: DrawnCandles,
  series: CandleSeries,
  { look, format, bars }: Painting
): DrawnCandles {
  each.api.applyOptions({
    upColor: look.upBody,
    downColor: look.downBody,
    borderUpColor: look.up,
    borderDownColor: look.down,
    wickUpColor: look.up,
    wickDownColor: look.down,
    borderVisible: true,
    wickVisible: true,
    priceFormat: { type: "price", ...format },
  })
  const close = series.close.at(-1)
  const colour = lastBarColour(look, series.open, series.close)
  each.lastPrice.applyOptions(
    close === undefined
      ? { lineVisible: false, axisLabelVisible: false }
      : {
          price: close,
          color: colour,
          lineVisible: true,
          axisLabelVisible: true,
          axisLabelColor: colour,
          axisLabelTextColor: legibleText(colour),
        }
  )
  if (bars) {
    each.api.setData(
      series.time.map((time, index) => ({
        time: chartTime(time),
        open: series.open[index],
        high: series.high[index],
        low: series.low[index],
        close: series.close[index],
      }))
    )
  }
  each.markers.setMarkers(
    (series.markers ?? []).map((marker) => drawnMarker(marker, look))
  )
  const sessions = series.sessions
  const spans = !bars
    ? each.spans
    : sessions === undefined
      ? []
      : sessionSpans(series.time, sessions)
  each.shading.shade(spans, look.sessionShade, look.sessionsShaded)
  const primitives = series.primitives ?? []
  each.primitives
    .filter((old) => !primitives.includes(old))
    .forEach((old) => each.api.detachPrimitive(old))
  primitives
    .filter((next) => !each.primitives.includes(next))
    .forEach((next) => each.api.attachPrimitive(next))
  return { ...each, spans, primitives, last: series }
}

/** Paint a histogram: its bars are set again with new bars, and where their colours follow the
 * look, by direction now or before, since a bar's own colour stays until its bars are set. */
function paintedHistogram(
  each: DrawnHistogram,
  series: HistogramSeries,
  { look, bars }: Painting
): DrawnHistogram {
  each.api.applyOptions({ color: look.volume })
  const rising = look.volumeByDirection ? series.rising : undefined
  const byDirection = rising !== undefined
  if (bars || byDirection || each.byDirection) {
    each.api.setData(
      series.time.map((time, index) => ({
        time: chartTime(time),
        value: series.value[index],
        ...(rising === undefined
          ? {}
          : { color: rising[index] ? look.volumeUp : look.volumeDown }),
      }))
    )
  }
  return { ...each, byDirection, last: series }
}

function drawnMarker(marker: ChartMarker, look: ChartLook): SeriesMarker<Time> {
  return {
    time: chartTime(marker.time),
    position: marker.position === "above" ? "aboveBar" : "belowBar",
    shape: marker.shape,
    color: look.markers[marker.tone],
    text: marker.text,
  }
}
