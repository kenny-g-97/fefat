# Charts

`PriceChart` draws price charts over [Lightweight Charts](https://tradingview.github.io/lightweight-charts/) 5.2.1 (Apache 2.0, step 5.4, D-93). The Data area's chart viewer is its first user; step 5.9's trade review chart and Phase 6's feature panes reuse it. `src/charts/` is the one place the library is imported, but for the types a caller's own primitive implements.

```tsx
<PriceChart
  label="MES, 5-minute bars"
  panes={[
    { id: "price", stretch: 3, series: [candles] },
    { id: "volume", stretch: 1, series: [volume] },
  ]}
  style={settings.chart_style}
  priceFormat={{ precision: 2, minMove: 0.25 }}
  wheel={pageScrolls ? "page" : "chart"}
  onVisibleBarsChange={({ before }) => before < 500 && loadOlder()}
  onCrosshairMove={(index) => setHovered(index)}
/>
```

Give it a parent that sets its size: it fills the box it is in (`autoSize`, inside an absolutely placed host, since the library sizes its own table in pixels and would never shrink in a flex item otherwise). On the chart's page that parent is a card in a frame the trader drags by its edges (`ResizableFrame` in `src/ui/resizable-frame.tsx`), and the chart redraws to it at every move of the pointer.

## Props

| Prop | What it is |
| --- | --- |
| `label` | The chart's name for a screen reader: the instrument and the timeframe. |
| `panes` | The panes top to bottom, each a `ChartPane`. Memoise them: a new array sets every series' bars again. |
| `style` | The trader's `ChartStyle` from `GET /v1/settings`, which the chart draws in the theme the page shows (`useShownTheme`), each colour the trader's own for that theme or else the theme's token from `web/DESIGN.md`. |
| `priceFormat` | The price axis's `precision`, the decimals of the instrument's tick (`decimalsOf` in `src/ui/figures.ts`), and its `minMove`, the tick. |
| `wheel` | `chart` lets the wheel zoom and pan the chart; `page` leaves it to the page, as the chart page does while some of the page's content lies under the window's foot, so that it never traps the page's scroll (`usePageScrolls`); a page longer than the window by no more than its own padding leaves the wheel to the chart. Dragging, the price axis, and the keys still move the chart. |
| `onVisibleBarsChange` | Told, after each draw and each pan or zoom, how many bars of the first candle series lie `before` the view and `after` it, as `VisibleBars`: the chart viewer loads an older window when fewer than 500 lie before it. |
| `onCrosshairMove` | Told the index of the bar under the crosshair in the first candle series' columns, or null when it leaves: the caller reads its own bar there, the API's numbers unchanged. |

## Panes and series

A `ChartPane` is `id`, `stretch`, its share of the height against the other panes, and `series`, drawn in its pane in order. A series is kept by its `id`: a series that keeps its id and its pane keeps its place, a new id adds one, and a pane whose last series goes is removed, so that a volume pane comes and goes without drawing the chart anew.

A `CandleSeries` (`kind`: `candles`) holds its bars column by column, as `GET /v1/market/bars` sends them:

- `id`, `time`, `open`, `high`, `low`, `close`: a bar's `time` is its open in whole seconds since the epoch, UTC, for intraday bars, or its trade date, `2026-03-06`, for daily bars, which the chart places by session; never a time shifted to a zone.
- `sessions`: each bar's trade date, by which the chart shades every other session behind the bars (`SessionShading`), counting back from the newest, so that older bars arriving change no session's shade. The style's `sessions_shaded` turns it off.
- `markers`: `ChartMarker`s, each a `time`, a `text`, a `position` above or below its bar, a `shape`, and a `tone`, `subtle`, `accent`, `positive`, or `negative`, which the look colours: the chart viewer marks each roll of a spliced series (`rollMarks`); step 5.9 marks fills in the sign colours.
- `primitives`: the caller's own Lightweight Charts series primitives, attached to this series and detached when they leave the list, such as step 5.9's entry-to-exit connectors and stop and target bands.

A `HistogramSeries` (`kind`: `histogram`), such as volume, holds `id`, `time`, and `value`, and, where its bars take their candle's colour when the style colours volume by direction, `rising`, whether each bar's close is at or above its open, the rule the candles follow.

## Time

The library has no time zones. The chart keeps true UTC seconds, and its labels show the browser's zone, as every instant of the app does: the crosshair's label and the readout give `2026-03-06 09:00`, and the axis's times of day are local (`chart-time.ts`). Its day, month, and year marks fall where the library puts them, on UTC days, so they read by the UTC date they mark; on CME's products a UTC day begins an hour or two after the session of the same trade date opens, so a day mark falls inside its trade date's session. Marks on the trader's own days need a horizontal scale of FEAT's own (`BACKLOG.md`).

## Look

`chartLook` turns the style and the theme into colours (`chart-look.ts`): FEAT's default is hollow candles, green rising and red falling, in `--positive` and `--negative`, the builder's exception to "colour means sign" (web/DESIGN.md), on a clear background so that the card shows through, with the grid in `--border` and the axis text in `--muted-foreground`; volume in `--input`, or by direction at half strength. The last price is a dashed line of the chart's own at the newest close, in its bar's direction colour (`lastBarColour`), its label on the axis written in ink or in white, whichever reads better on that colour (`legibleText`): the library's own label would follow the last bar in view as the trader scrolls back, and its text falls under 3 : 1 on the dark theme's sign colours. The volume shows no last value; the caller's readout gives it. A change of the look recolours the series without setting their bars again, but for volume by direction, whose bars carry their own colours.

The library's licence, Apache 2.0, asks an app for two things on a page its users see: a link to TradingView and the library's attribution notice. The link is the attribution logo, which stays in the chart's corner (`attributionLogo`); the library writes a style element for it, which the content security policy allows from step 5.4, and `src/index.css` gives it the subtle text colour. The notice is `CHART_NOTICE` in `attribution.ts`, word for word from the NOTICE file of the library's tag v5.2.1, which the settings' About shows; read that file again when the library is upgraded, since its text may change with the version, as `attribution.test.ts` reminds by pinning the version beside the copy. The bundle's own banner prints its build's year, 2026, and a Latin letter; the notice is the file's.

## Keys

The chart takes the focus on a click or Tab, and then: the arrows pan a tenth of the bars in view, PageUp and PageDown a screen, Home and End go at once to the earliest and the latest bar loaded, and plus and minus zoom (`chart-keys.ts`). Its focus outline lies 2 px inside it, since a card around it may clip what lies outside.

## Tests

The pure parts have vitest's tests beside them: the look, the labels in a zone with daylight saving (`vite.config.ts` runs vitest in America/Chicago), the keys, the sessions' shading, the roll marks, and this file naming every prop and field (Done means 3 of step 5.4). The drawing itself runs in a browser alone: `web/e2e/chart.spec.ts` reads the canvas's pixels, the readout, and the requests.

# The results' charts

`EquityChart`, `HistogramChart`, `FanChart`, and `PercentileChart` draw a finished run's results (steps 5.7, 5.20, and 5.21, D-116, D-118, D-120) from columns the server worked out; none computes a figure.

`EquityChart`, `FanChart`, and `PercentileChart` draw over [Apache ECharts](https://echarts.apache.org/) 6.1.0 (Apache 2.0, D-93) through `PointedChart`, which alone imports the library, registering its parts: the line chart, the grid, the tooltip with its axis pointer, the mark line, the piecewise visual map, which colours a line by its value, and the canvas renderer. `PointedChart` fills its box, redraws when it resizes and when the theme changes, and tells its caller the entry under the pointer or the keys, for the caller's own readout, its keys stepping from the entry pointed at, or else from `rest`, the entry the readout shows meanwhile, the last unless a chart gives another; each chart hands it a function from the theme's tokens to the library's options, `equityOption` in `equity-option.ts`, `fanOption` in `fan-option.ts`, and `percentileOption` in `percentile-option.ts`, pure functions that vitest reads and that share their axes, pointer, and dashed lines at the capital and at the run's own figure (`results-chart.ts`). Each chart loads with the first card that draws it (`lazyRouteComponent`, which reloads the page once when a rebuild replaced its chunk), out of the app's first bundle, and the settings' About carries the library's notice (`EQUITY_CHART_NOTICE`, which a test holds to the installed package's NOTICE file).

## EquityChart

`EquityChart` draws the equity curve over its drawdown.

```tsx
<div className="h-80">
  <EquityChart
    label="Equity and drawdown of this run"
    curve={curve}
    currency={statistics.currency}
    pointed={pointed}
    onPointed={setPointed}
  />
</div>
```

| Prop | What it is |
| --- | --- |
| `label` | The chart's name for a screen reader. |
| `curve` | `GET /v1/runs/{run}/equity`: the `capital`, and one entry a decision in `time` (whole seconds), `equity`, and `drawdown`, a depth below the peak. |
| `currency` | The run's currency, from `GET /v1/runs/{run}/stats`, which both value axes' labels write their money in, `$50,000` (D-117). |
| `pointed` | The decision the readout shows, from `onPointed`, which the keys step from. |
| `onPointed` | Told the index of the decision under the pointer or the keys, or null when the pointer leaves the chart, Escape is pressed, or the focus moves off it within the page: the caller's readout then shows the last decision. Between the two panes, where no decision lies, it is told nothing, so that the readout holds. |

Give it a parent that sets its height; it fills that box and redraws when it resizes. `equityOption` turns the columns and the theme's tokens into the library's options: the equity over a dashed line at the capital, its line and its fill to the capital in the sign colours, green above the capital and red below (D-119), through a piecewise visual map, since a line's own colour would override the map's; ECharts colours a line by its value from the pieces closed at both ends alone and reads which way the axis runs from their ends, so the positive takes one from the capital to a unit of money above it, where a piece of no height would turn the colours upside down, and a run that never leaves its capital takes the capital line's grey; and under it, on one time axis, the drawdown in grey, its axis inverted so that the depth hangs from zero with no figure negated. Nothing animates, its axis pointer included, and it offers no zoom, so the wheel scrolls the page. The chart takes the focus on a click or Tab, and then Left and Right step a decision, Home and End go to either end, and Escape or moving the focus off it gives the readout back to the last, while the window going away keeps the reading; a key with Alt, Ctrl, or Command stays the browser's.

## HistogramChart

`HistogramChart` draws one of `GET /v1/runs/{run}/distribution`'s histograms as bars in the page, so that each names its range and its count to a pointer and a screen reader (`-150 to -140: 3 trades`), and a test reads them.

| Prop | What it is |
| --- | --- |
| `testId` | Its `data-testid`. |
| `label` | The measure and its unit, over the bars. |
| `note` | Optional, a few words beside the label, such as how many trades have no stop. |
| `bins` | The server's `lower`, `upper`, and `trades`, one entry a bin. |
| `signed` | For a measure either side of zero: its bins in the sign colours with a mark at zero, the others in grey. |
| `edge` | Optional, how an edge is written, such as money in the run's currency, `-$150` (D-117); the decimals it holds by default, `-1.5`. |

## FanChart

`FanChart` draws the equity fan of a run's Monte Carlo (step 5.20, D-118), its paths' equity by the count of trades made, in the equity chart's idiom.

```tsx
<div className="h-80">
  <FanChart
    label="Equity of the paths by trades made"
    fan={report.fan}
    currency={statistics.currency}
    pointed={pointed}
    onPointed={setPointed}
  />
</div>
```

| Prop | What it is |
| --- | --- |
| `label` | The chart's name for a screen reader. |
| `fan` | `GET /v1/runs/{run}/monte-carlo`'s `fan`: the `capital`, and one entry a count in `trades_made`, from none to the run's trades, in the paths' `p5`, `p25`, `median`, `p75`, and `p95` equity, and in `own`, the run's own equity after as many of its trades in the order made (step 5.21). |
| `currency` | The run's currency, which the value axis's labels write their money in. |
| `pointed` | The count the readout shows, as its index in the fan's columns, from `onPointed`, which the keys step from. |
| `onPointed` | Told the index of the count under the pointer or the keys, or null when the pointer leaves the chart, Escape is pressed, or the focus moves off it within the page: the caller's readout then shows the last count. |

`fanOption` draws the median in the accent and the run's own walk over it in the purple (D-119), over the dashed line at the capital, and behind them, as layers of one stack, the paths from their 5th to their 95th percentile in the field border's grey at 30 % and the middle half, from the 25th to the 75th, at 45 %, where both lines keep 3 : 1 in either theme, each layer as tall as the gap between two of the API's percentiles, so that its top stands at the higher; the counts run along a value axis from none to the run's trades, in whole numbers. It never animates and has no zoom, and its keys are the equity chart's.

## PercentileChart

`PercentileChart` draws one figure of a run's Monte Carlo against the percent of its paths (step 5.21, D-120), as NinjaTrader's Monte Carlo draws it, in the equity chart's idiom.

```tsx
<div className="h-80">
  <PercentileChart
    label="Max drawdown of the paths at each percent of them, beside this run's"
    figure={report.by_percent.max_drawdown}
    currency={statistics.currency}
    rest={50}
    pointed={pointed}
    onPointed={setPointed}
  />
</div>
```

| Prop | What it is |
| --- | --- |
| `label` | The chart's name for a screen reader. |
| `figure` | One of `GET /v1/runs/{run}/monte-carlo`'s `by_percent`: `at_percent`, the paths' figure at each whole percent from 0 to 100, the path at the nearest rank of the paths ordered from the lowest, null for a path without a profit factor, which stands above every other, and the run's `own`, null for a run without a losing trade. |
| `currency` | The run's currency where the figure is money, which the value axis's labels write it in, `$1,500`; null for ticks and the profit factor, written plain, `1.25`. |
| `rest` | The percent the keys step from while nothing is pointed at, which the caller's readout shows meanwhile: the median path, 50. |
| `pointed` | The percent the readout shows, from `onPointed`. |
| `onPointed` | Told the percent under the pointer or the keys, or null when the pointer leaves the chart, Escape is pressed, or the focus moves off it within the page: the caller's readout then shows `rest`. |

`percentileOption` draws the paths' figure in the accent from none of the paths to all of them, a gap where a path has none, and the run's own figure as a dashed line in the purple (D-119), the axis kept to show it where it stands past every path; the percents run along a value axis from 0 to 100, labelled every tenth. A figure no path has is refused, since its chart has nothing to draw: the card says why in its place. It never animates and has no zoom, and its keys are the equity chart's.
