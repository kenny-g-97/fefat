import type {
  IPrimitivePaneView,
  ISeriesPrimitive,
  Time,
} from "lightweight-charts"
import type { ChartPane } from "./drawn-series"

/** A series primitive that draws nothing and tells `onChange` each time the chart works its
 * views out again, after a pan, a zoom, a resize, a change of the price axis's range, or new
 * bars, never for a move of the crosshair alone: what lies over the chart in the page, such as
 * a tooltip pinned to a fill, then takes its place again (`PriceChart`'s `onViewChange`). */
export class ViewWatch implements ISeriesPrimitive<Time> {
  private readonly views: readonly IPrimitivePaneView[] = []
  private readonly onChange: () => void

  constructor(onChange: () => void) {
    this.onChange = onChange
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views
  }

  updateAllViews(): void {
    this.onChange()
  }
}

/** `panes` with `watch` among the primitives of their first candle series, so that it follows
 * the series as the chart draws it again; as they are where they hold none. */
export function watched(
  panes: readonly ChartPane[],
  watch: ViewWatch
): readonly ChartPane[] {
  const first = panes
    .flatMap((pane) => pane.series)
    .find((series) => series.kind === "candles")
  if (first === undefined) {
    return panes
  }
  return panes.map((pane) => ({
    ...pane,
    series: pane.series.map((series) =>
      series === first && series.kind === "candles"
        ? { ...series, primitives: [...(series.primitives ?? []), watch] }
        : series
    ),
  }))
}
