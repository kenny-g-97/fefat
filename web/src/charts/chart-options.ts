import {
  type ChartOptions,
  ColorType,
  CrosshairMode,
  type DeepPartial,
  type IChartApi,
  type Time,
  TickMarkType,
} from "lightweight-charts"
import type { KeyAction } from "./chart-keys"
import type { ChartLook } from "./chart-look"
import {
  barTime,
  crosshairTime,
  type TickMark,
  tickMarkLabel,
} from "./chart-time"

const TICK_MARKS: Readonly<Record<TickMarkType, TickMark>> = {
  [TickMarkType.Year]: "year",
  [TickMarkType.Month]: "month",
  [TickMarkType.DayOfMonth]: "day",
  [TickMarkType.Time]: "time",
  [TickMarkType.TimeWithSeconds]: "seconds",
}

/** The options a price chart is created with, which no style changes: its font, its labels in
 * the browser's zone, its axes, and its crosshair. */
export function fixedOptions(): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      fontFamily: '"Geist Mono", ui-monospace, monospace',
      fontSize: 12,
      attributionLogo: true,
      panes: { enableResize: false },
    },
    localization: {
      timeFormatter: (time: Time) => crosshairTime(barTime(time)),
    },
    timeScale: {
      borderVisible: false,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time: Time, mark: TickMarkType) =>
        tickMarkLabel(barTime(time), TICK_MARKS[mark]),
    },
    rightPriceScale: { borderVisible: false, minimumWidth: 40 },
    grid: { vertLines: { visible: false } },
    crosshair: { mode: CrosshairMode.Normal },
  }
}

/** The options of `look`, and whether the wheel moves the chart or leaves the page to scroll. */
export function lookOptions(
  look: ChartLook,
  wheel: "chart" | "page"
): DeepPartial<ChartOptions> {
  const line = {
    color: look.crosshair,
    labelBackgroundColor: look.crosshairLabel,
  }
  const wheeled = wheel === "chart"
  return {
    layout: {
      background: { type: ColorType.Solid, color: look.background },
      textColor: look.text,
      panes: { separatorColor: look.grid, separatorHoverColor: look.grid },
    },
    grid: { horzLines: { visible: look.gridShown, color: look.grid } },
    crosshair: { vertLine: line, horzLine: line },
    handleScroll: {
      mouseWheel: wheeled,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: false,
    },
    handleScale: {
      mouseWheel: wheeled,
      pinch: true,
      axisPressedMouseMove: true,
    },
  }
}

/** Pan, zoom, or go to the earliest or the latest bar loaded, as `action` asks. */
export function moved(
  chart: IChartApi,
  action: Exclude<KeyAction, Readonly<{ kind: "step" }>>
): void {
  const timeScale = chart.timeScale()
  if (action.kind === "latest") {
    timeScale.scrollToPosition(timeScale.options().rightOffset, false)
    return
  }
  if (action.kind === "zoom") {
    timeScale.applyOptions({
      barSpacing: timeScale.options().barSpacing * action.factor,
    })
    return
  }
  const range = timeScale.getVisibleLogicalRange()
  if (range === null) {
    return
  }
  const width = range.to - range.from
  const from =
    action.kind === "earliest" ? 0 : range.from + width * action.screens
  timeScale.setVisibleLogicalRange({ from, to: from + width })
}
