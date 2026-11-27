import type { BarColumns } from "@/api/bar-windows"
import type { ChartFill, ChartTrade, ChartWindow } from "@/api/run-chart"
import { chartPanes } from "@/charts/bar-panes"
import type { ChartLook } from "@/charts/chart-look"
import type { ChartMarker } from "@/charts/chart-marks"
import { withAlpha } from "@/charts/chart-look"
import type { ReadoutField } from "@/charts/ChartReadout"
import type { ChartTime } from "@/charts/chart-time"
import type { ChartPane, LineSeries } from "@/charts/drawn-series"
import type { TradeOverlay, TradeOverlayView } from "@/charts/trade-overlay"
import { formatFeature, moneySign } from "@/ui/figures"

/** A fill drawn on the chart: its marker's id, the bar it stands on, its price, and its trade. */
export type DrawnFill = Readonly<{
  id: string
  time: ChartTime
  price: number
  fill: ChartFill
  trade: ChartTrade
}>

/** A band behind a line keeps the line legible over it (web/DESIGN.md, Palette, Charts). */
const BAND_ALPHA = 0.12
/** The selected trade's markers stand out from the others' by their size. */
const SELECTED_SIZE = 2

/** Where each bar of `bars` stands on the time axis: its open, or its trade date for daily bars,
 * which the chart places by session. */
export function barPlaces(
  bars: BarColumns,
  daily: boolean
): ReadonlyMap<number, ChartTime> {
  return new Map(
    bars.time.map((time, index): [number, ChartTime] => [
      time,
      daily ? bars.trade_date[index] : time,
    ])
  )
}

/** The id of the marker of the `index`th fill of `trade`: its entry order, then the place. */
export function fillId(trade: ChartTrade, index: number): string {
  return `${trade.entry_order}/${index}`
}

/** Each fill of the window's trades that lies on its bars, by its marker's id, which names the
 * trade's entry order and the fill's place among its fills. */
export function drawnFills(
  chart: ChartWindow,
  places: ReadonlyMap<number, ChartTime>
): ReadonlyMap<string, DrawnFill> {
  return new Map(
    chart.trades.flatMap((trade) =>
      trade.fills.flatMap((fill, index): [string, DrawnFill][] => {
        const time =
          fill.bar_time === null ? undefined : places.get(fill.bar_time)
        const id = fillId(trade, index)
        return time === undefined
          ? []
          : [[id, { id, time, price: Number(fill.price), fill, trade }]]
      })
    )
  )
}

/** The chart's panes: the candles, their rolls and sessions marked as the Data chart marks them,
 * with every drawn fill at its price, a buy's arrow under it in the positive and a sell's above it
 * in the negative, the selected trade's larger, and the overlay of connectors and bands; the
 * volume while the style shows it; and a pane a feature, its line beside the bars. */
export function tradePanes(
  chart: ChartWindow,
  timeframe: string,
  volumeShown: boolean,
  fills: ReadonlyMap<string, DrawnFill>,
  shown: Readonly<{ selected: number | null; overlay: TradeOverlay }>
): readonly ChartPane[] {
  const [price, ...rest] = chartPanes(chart.bars, timeframe, volumeShown)
  const time = barTimes(chart.bars, timeframe === "1d")
  const priced = price.series.map((series) =>
    series.kind === "candles"
      ? {
          ...series,
          markers: [
            ...(series.markers ?? []),
            ...onePerFill([...fills.values()], shown.selected).map((each) =>
              fillMarker(each, shown.selected)
            ),
          ],
          primitives: [shown.overlay],
        }
      : series
  )
  const features = chart.features.map((feature): ChartPane => ({
    id: `feature-${feature.name}`,
    stretch: 1,
    series: [featureLine(feature.name, time, feature.values)],
  }))
  return [{ ...price, stretch: 3, series: priced }, ...rest, ...features]
}

function barTimes(bars: BarColumns, daily: boolean): readonly ChartTime[] {
  return daily ? bars.trade_date : bars.time
}

function featureLine(
  name: string,
  time: readonly ChartTime[],
  values: readonly (number | null)[]
): LineSeries {
  return { kind: "line", id: `feature-${name}`, time, value: values }
}

/** `fills`, one a fill of the ledger: a fill that reverses a position stands under both of its
 * trades (S-fill-042), and is drawn once, as the selected trade's where it is one of them. */
function onePerFill(
  fills: readonly DrawnFill[],
  selected: number | null
): readonly DrawnFill[] {
  const drawn = new Map<string, DrawnFill>()
  for (const each of fills) {
    const key = `${each.fill.order} ${each.fill.time}`
    if (!drawn.has(key) || each.trade.trade === selected) {
      drawn.set(key, each)
    }
  }
  return [...drawn.values()]
}

function fillMarker(drawn: DrawnFill, selected: number | null): ChartMarker {
  const buys = drawn.fill.side === "buy"
  return {
    time: drawn.time,
    text: "",
    position: buys ? "below" : "above",
    shape: buys ? "arrowUp" : "arrowDown",
    tone: buys ? "positive" : "negative",
    price: drawn.price,
    id: drawn.id,
    ...(drawn.trade.trade === selected ? { size: SELECTED_SIZE } : {}),
  }
}

/** What the overlay draws: each trade's line from its entry to its last fill, in its net P&L's
 * sign colour, solid for the selected trade and dashed for the others; and behind the selected
 * trade, from its entry's bar to its exit's, the band to its stop's first level in the negative
 * and the band to its furthest target in the positive, at a share of the colour, with its stop's
 * last level dashed where a breakeven, a trail, or a roll moved it. A trade whose entry or exit
 * lies off the bars read draws nothing yet. */
export function overlayView(
  chart: ChartWindow,
  fills: ReadonlyMap<string, DrawnFill>,
  selected: number | null,
  colours: ChartLook["markers"]
): TradeOverlayView {
  const ends = chart.trades.flatMap((trade) => {
    const entry = fills.get(fillId(trade, 0))
    const exit = fills.get(fillId(trade, trade.fills.length - 1))
    return entry === undefined || exit === undefined || entry === exit
      ? []
      : [{ trade, entry, exit }]
  })
  const colourOf = (trade: ChartTrade) =>
    moneySign(trade.pnl) === "negative" ? colours.negative : colours.positive
  const chosen = ends.find((each) => each.trade.trade === selected)
  return {
    connectors: ends.map(({ trade, entry, exit }) => ({
      from: { time: entry.time, price: entry.price },
      to: { time: exit.time, price: exit.price },
      colour: colourOf(trade),
      selected: trade.trade === selected,
    })),
    ...(chosen === undefined
      ? { bands: [], levels: [] }
      : bracket(chosen, colours)),
  }
}

function bracket(
  chosen: Readonly<{ trade: ChartTrade; entry: DrawnFill; exit: DrawnFill }>,
  colours: ChartLook["markers"]
): Pick<TradeOverlayView, "bands" | "levels"> {
  const { trade, entry, exit } = chosen
  const span = { from: entry.time, to: exit.time }
  const stop = trade.stop.first === null ? null : Number(trade.stop.first)
  const targets = trade.targets.map(Number)
  const furthest = targets.toSorted(
    (one, other) => Math.abs(other - entry.price) - Math.abs(one - entry.price)
  )[0]
  const band = (level: number, colour: string) => ({
    ...span,
    low: Math.min(level, entry.price),
    high: Math.max(level, entry.price),
    colour: withAlpha(colour, BAND_ALPHA),
  })
  const moved = trade.stop.last !== null && trade.stop.last !== trade.stop.first
  return {
    bands: [
      ...(stop === null ? [] : [band(stop, colours.negative)]),
      ...(furthest === undefined ? [] : [band(furthest, colours.positive)]),
    ],
    levels:
      moved && trade.stop.last !== null
        ? [
            {
              ...span,
              price: Number(trade.stop.last),
              colour: colours.negative,
            },
          ]
        : [],
  }
}

/** The fill a tooltip names, and whether it is pinned there by the selection. */
export type TooltipFill = Readonly<{ drawn: DrawnFill; pinned: boolean }>

/** The fill the chart's tooltip names (web/DESIGN.md, Patterns, Marker tooltip): the marker
 * under the pointer; else a fill on the bar under the crosshair, the pointer's or the keys', the
 * selected trade's first; else the selected trade's entry, pinned; none where no fill applies. */
export function tooltipFill(
  chart: ChartWindow,
  fills: ReadonlyMap<string, DrawnFill>,
  selected: number | null,
  pointer: Readonly<{ hovered: string | null; crosshair: number | null }>
): TooltipFill | null {
  const hovered =
    pointer.hovered === null ? undefined : fills.get(pointer.hovered)
  if (hovered !== undefined) {
    return { drawn: hovered, pinned: false }
  }
  // Left of the first bar the library's index is negative, which names no bar.
  const barTime =
    pointer.crosshair === null ? undefined : chart.bars.time[pointer.crosshair]
  const onTheBar = [...fills.values()]
    .filter((each) => each.fill.bar_time === barTime)
    .toSorted((one, other) => rank(one, selected) - rank(other, selected))
    .at(0)
  if (onTheBar !== undefined) {
    return { drawn: onTheBar, pinned: false }
  }
  const trade = chart.trades.find((each) => each.trade === selected)
  const entry = trade === undefined ? undefined : fills.get(fillId(trade, 0))
  return entry === undefined ? null : { drawn: entry, pinned: true }
}

function rank(drawn: DrawnFill, selected: number | null): number {
  return drawn.trade.trade === selected ? 0 : 1
}

/** The index among the chart's bars of the bar the selected trade's entry lies on, which the
 * readout shows while the crosshair stands on none; none without a selection drawn, the readout
 * then showing the last bar. */
export function entryBar(
  chart: ChartWindow,
  fills: ReadonlyMap<string, DrawnFill>,
  selected: number | null
): number | null {
  const trade = chart.trades.find((each) => each.trade === selected)
  const entry = trade === undefined ? undefined : fills.get(fillId(trade, 0))
  const at =
    entry === undefined || entry.fill.bar_time === null
      ? -1
      : chart.bars.time.indexOf(entry.fill.bar_time)
  return at === -1 ? null : at
}

/** The figures the readout adds of the bar `at`: each feature's value there, under its name. */
export function featureFields(
  chart: ChartWindow
): (at: number) => readonly ReadoutField[] {
  return (at) =>
    chart.features.map((feature) => {
      const value = feature.values.at(at)
      if (value === undefined) {
        throw new Error(
          `Expected a value of ${feature.name} for each of the chart's bars, got none at ${at}.`
        )
      }
      return {
        label: feature.name,
        id: `feature-${feature.name}`,
        value: formatFeature(value),
      }
    })
}
