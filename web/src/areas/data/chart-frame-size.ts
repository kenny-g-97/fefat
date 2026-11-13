import { useState } from "react"
import { FILLS, type FrameSize } from "@/ui/frame-size"

/** The least the chart's frame may be, where the readout's prices and the candles still read,
 * and the most it may be tall; its most width is its column's. */
export const CHART_FRAME = {
  leastWidth: 576,
  leastHeight: 240,
  mostHeight: 1600,
}

/** The size the trader gave the chart's frame, and the way to change it; it fills its page
 * until an edge is dragged. */
export function useChartFrameSize(): readonly [
  FrameSize,
  (size: FrameSize) => void,
] {
  const [size, setSize] = useState<FrameSize>(FILLS)
  return [size, setSize]
}
