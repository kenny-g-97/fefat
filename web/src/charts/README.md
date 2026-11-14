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
