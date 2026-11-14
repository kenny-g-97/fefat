import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts"
import type { SessionSpan } from "./chart-marks"
import { chartTime } from "./chart-time"

/** Every other session of a candle series shaded behind its bars by their trade dates, a
 * Lightweight Charts series primitive (`README.md`). */
export class SessionShading implements ISeriesPrimitive<Time> {
  private chart: IChartApiBase<Time> | null = null
  private requestUpdate: (() => void) | null = null
  private spans: readonly SessionSpan[] = []
  private colour = "rgba(0, 0, 0, 0)"
  private readonly views: readonly IPrimitivePaneView[] = [
    { zOrder: () => "bottom", renderer: () => this.renderer() },
  ]

  attached({ chart, requestUpdate }: SeriesAttachedParameter<Time>): void {
    this.chart = chart
    this.requestUpdate = requestUpdate
  }

  detached(): void {
    this.chart = null
    this.requestUpdate = null
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views
  }

  /** Shade `spans`' shaded sessions in `colour`, none while `shown` is false. */
  shade(spans: readonly SessionSpan[], colour: string, shown: boolean): void {
    this.spans = shown ? spans.filter((span) => span.shaded) : []
    this.colour = colour
    this.requestUpdate?.()
  }

  private renderer(): IPrimitivePaneRenderer {
    return {
      draw: (target) => {
        const chart = this.chart
        if (chart === null || this.spans.length === 0) {
          return
        }
        const timeScale = chart.timeScale()
        const half = timeScale.options().barSpacing / 2
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          context.fillStyle = this.colour
          for (const span of this.spans) {
            const left = timeScale.timeToCoordinate(chartTime(span.first))
            const right = timeScale.timeToCoordinate(chartTime(span.last))
            if (
              left !== null &&
              right !== null &&
              right + half >= 0 &&
              left - half <= mediaSize.width
            ) {
              context.fillRect(
                left - half,
                0,
                right - left + 2 * half,
                mediaSize.height
              )
            }
          }
        })
      },
    }
  }
}
