import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts"
import { type ChartTime, chartTime } from "./chart-time"

/** A point of a trade on the chart: a bar's place on the time axis and a price. */
export type TradePoint = Readonly<{ time: ChartTime; price: number }>

/** A trade's line from its entry's fill to the fill that left it flat, in its result's colour,
 * solid for the selected trade. */
export type TradeConnector = Readonly<{
  from: TradePoint
  to: TradePoint
  colour: string
  selected: boolean
}>

/** A band behind the selected trade from its entry's bar to its exit's, between two prices: its
 * entry and its stop, or its entry and its target. */
export type TradeBand = Readonly<{
  from: ChartTime
  to: ChartTime
  low: number
  high: number
  colour: string
}>

/** A level as a dashed line from one bar to another, as a stop a breakeven or a trail moved. */
export type TradeLevel = Readonly<{
  from: ChartTime
  to: ChartTime
  price: number
  colour: string
}>

/** What the overlay draws: the bands first, then the levels, then the connectors. */
export type TradeOverlayView = Readonly<{
  bands: readonly TradeBand[]
  levels: readonly TradeLevel[]
  connectors: readonly TradeConnector[]
}>

const NOTHING: TradeOverlayView = { bands: [], levels: [], connectors: [] }
const DASH = [4, 4]

/** The trade review's connectors, bands, and levels over a candle series, a Lightweight Charts
 * series primitive (`README.md`), drawn behind the bars and their markers. */
export class TradeOverlay implements ISeriesPrimitive<Time> {
  private chart: IChartApiBase<Time> | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private view: TradeOverlayView = NOTHING
  private readonly views: readonly IPrimitivePaneView[] = [
    { zOrder: () => "bottom", renderer: () => this.renderer() },
  ]

  attached({
    chart,
    series,
    requestUpdate,
  }: SeriesAttachedParameter<Time>): void {
    this.chart = chart
    this.series = series
    this.requestUpdate = requestUpdate
  }

  detached(): void {
    this.chart = null
    this.series = null
    this.requestUpdate = null
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views
  }

  /** Draw `view` from now on. */
  show(view: TradeOverlayView): void {
    this.view = view
    this.requestUpdate?.()
  }

  private renderer(): IPrimitivePaneRenderer {
    return {
      draw: (target) => {
        const located = this.locator()
        if (located === null) {
          return
        }
        target.useMediaCoordinateSpace(({ context }) => {
          for (const band of this.view.bands) {
            drawBand(context, located, band)
          }
          for (const level of this.view.levels) {
            drawLine(context, located, level, level.price, level.colour)
          }
          for (const connector of this.view.connectors) {
            drawConnector(context, located, connector)
          }
        })
      },
    }
  }

  private locator(): Locator | null {
    const chart = this.chart
    const series = this.series
    if (chart === null || series === null) {
      return null
    }
    const timeScale = chart.timeScale()
    return {
      x: (time) => timeScale.timeToCoordinate(chartTime(time)),
      y: (price) => series.priceToCoordinate(price),
    }
  }
}

type Locator = Readonly<{
  x: (time: ChartTime) => number | null
  y: (price: number) => number | null
}>

function drawBand(
  context: CanvasRenderingContext2D,
  at: Locator,
  band: TradeBand
): void {
  const [left, right] = [at.x(band.from), at.x(band.to)]
  const [top, bottom] = [at.y(band.high), at.y(band.low)]
  if (left === null || right === null || top === null || bottom === null) {
    return
  }
  context.fillStyle = band.colour
  context.fillRect(left, top, Math.max(1, right - left), bottom - top)
}

function drawLine(
  context: CanvasRenderingContext2D,
  at: Locator,
  span: Readonly<{ from: ChartTime; to: ChartTime }>,
  price: number,
  colour: string
): void {
  const [left, right, y] = [at.x(span.from), at.x(span.to), at.y(price)]
  if (left === null || right === null || y === null) {
    return
  }
  context.strokeStyle = colour
  context.lineWidth = 1
  context.setLineDash(DASH)
  context.beginPath()
  context.moveTo(left, y)
  context.lineTo(right, y)
  context.stroke()
  context.setLineDash([])
}

function drawConnector(
  context: CanvasRenderingContext2D,
  at: Locator,
  connector: TradeConnector
): void {
  const [x1, y1] = [at.x(connector.from.time), at.y(connector.from.price)]
  const [x2, y2] = [at.x(connector.to.time), at.y(connector.to.price)]
  if (x1 === null || y1 === null || x2 === null || y2 === null) {
    return
  }
  context.strokeStyle = connector.colour
  context.lineWidth = connector.selected ? 2 : 1
  context.setLineDash(connector.selected ? [] : DASH)
  context.beginPath()
  context.moveTo(x1, y1)
  context.lineTo(x2, y2)
  context.stroke()
  context.setLineDash([])
}
