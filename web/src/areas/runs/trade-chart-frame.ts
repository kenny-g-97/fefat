import type { FrameSize } from "@/ui/frame-size"

/** Where this browser keeps the size the trader gave the trade review's frame, apart from the
 * chart viewer's, and the size it has until then: the column's width, 384 px tall, so that the
 * table stands under it in a window 800 px tall (the builder's answer at step 5.9's plan). */
export const TRADE_CHART_FRAME: Readonly<{
  keptAs: string
  fallback: FrameSize
}> = {
  keptAs: "fefat_trade_chart_frame_size",
  fallback: { width: null, height: 384 },
}
