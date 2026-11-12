import {
  CandlestickSeries,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ISeriesPrimitive,
  type SeriesMarker,
  type Time,
} from "lightweight-charts"
import { type ChartLook, lastBarColour } from "./chart-look"
import { type ChartMarker, sessionSpans } from "./chart-marks"
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
  pane: number
  api: ISeriesApi<"Candlestick">
  markers: ISeriesMarkersPluginApi<Time>
  shading: SessionShading
  primitives: readonly ISeriesPrimitive<Time>[]
  last: CandleSeries
}

type DrawnHistogram = {
  kind: "histogram"
  pane: number
  api: ISeriesApi<"Histogram">
  last: HistogramSeries
}

/** A series the chart draws, with what it last drew. */
export type Drawn = DrawnCandles | DrawnHistogram

type Wanted = Readonly<{ series: ChartSeries; pane: number }>

/** Draw `panes` on `chart`: remove the series `drawn` holds that `panes` lacks or moves, add
 * those it lacks in pane order, a pane made for each new one, and give each its bars, markers,
 * shading, and primitives in `look`. */
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
    if (
      want === undefined ||
      want.series.kind !== each.kind ||
      want.pane !== each.pane
    ) {
      chart.removeSeries(each.api)
      drawn.delete(id)
    }
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
  if (series.kind === "histogram") {
    const api = chart.addSeries(
      HistogramSeries,
      { priceFormat: { type: "volume" } },
      pane
    )
    return { kind: "histogram", pane, api, last: series }
  }
  const api = chart.addSeries(CandlestickSeries, {}, pane)
  const shading = new SessionShading()
  api.attachPrimitive(shading)
  const markers = createSeriesMarkers(api, [])
  return {
    kind: "candles",
    pane,
    api,
    markers,
    shading,
    primitives: [],
    last: series,
  }
}

function painted(each: Drawn, series: ChartSeries, painting: Painting): Drawn {
  if (each.kind === "candles" && series.kind === "candles") {
    return paintedCandles(each, series, painting)
  }
  if (each.kind === "histogram" && series.kind === "histogram") {
    return paintedHistogram(each, series, painting.look)
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
    priceLineColor: lastBarColour(look, series.open, series.close),
    priceFormat: { type: "price", ...format },
  })
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
  const spans =
    series.sessions === undefined
      ? []
      : sessionSpans(series.time, series.sessions)
  each.shading.shade(spans, look.sessionShade, look.sessionsShaded)
  const primitives = series.primitives ?? []
  each.primitives
    .filter((old) => !primitives.includes(old))
    .forEach((old) => each.api.detachPrimitive(old))
  primitives
    .filter((next) => !each.primitives.includes(next))
    .forEach((next) => each.api.attachPrimitive(next))
  return { ...each, primitives, last: series }
}

function paintedHistogram(
  each: DrawnHistogram,
  series: HistogramSeries,
  look: ChartLook
): DrawnHistogram {
  each.api.applyOptions({ color: look.volume })
  const rising = series.rising
  each.api.setData(
    series.time.map((time, index) => ({
      time: chartTime(time),
      value: series.value[index],
      ...(look.volumeByDirection && rising !== undefined
        ? { color: rising[index] ? look.volumeUp : look.volumeDown }
        : {}),
    }))
  )
  return { ...each, last: series }
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
