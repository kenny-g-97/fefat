import { useState } from "react"
import { z } from "zod"
import { FILLS, type FrameSize } from "@/ui/frame-size"

/** The least the chart's frame may be, where the readout and the candles still read, and the
 * most it may be tall in a window no taller than that; its most width is its column's. */
export const CHART_FRAME: Readonly<{
  leastWidth: number
  leastHeight: number
  mostHeight: number
}> = {
  leastWidth: 576,
  leastHeight: 240,
  mostHeight: 1600,
}

const KEPT_AS = "fefat_chart_frame_size"
const keptSize = z.object({
  width: z.number().int().min(CHART_FRAME.leastWidth).nullable(),
  height: z.number().int().min(CHART_FRAME.leastHeight).nullable(),
})

/** The size `text` holds, as the browser's local storage kept it; a frame that fills where
 * nothing is kept, or where what is kept is no size of the chart's: the storage is the trader's
 * to edit, and another version's to have written. A size past the frame's most is a size
 * still, wider than the column or taller than this window allows, and the frame draws it at
 * its most. */
export function storedFrameSize(text: string | null): FrameSize {
  const read = keptSize.safeParse(text === null ? null : parsed(text))
  return read.success ? read.data : FILLS
}

/** The size the trader gave the chart's frame, and the way to change it. It is kept in this
 * browser's local storage, since a size in pixels suits one screen, and read where the frame is
 * drawn, so that another timeframe's chart stands in the frame as the trader left it. */
export function useChartFrameSize(): readonly [
  FrameSize,
  (size: FrameSize) => void,
] {
  const [size, setSize] = useState(keptFrameSize)
  const resize = (next: FrameSize) => {
    setSize(next)
    // shortcut: written at every move of a drag, a few bytes some hundred times a second;
    // write once as the drag ends if a profile ever shows it.
    keep(next)
  }
  return [size, resize]
}

function parsed(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function keptFrameSize(): FrameSize {
  try {
    return storedFrameSize(localStorage.getItem(KEPT_AS))
  } catch {
    // A browser that refuses its storage, as a private window may, keeps nothing.
    return FILLS
  }
}

function keep(size: FrameSize): void {
  try {
    localStorage.setItem(KEPT_AS, JSON.stringify(size))
  } catch {
    // Storage refused or full: the size holds until another chart is drawn, by a change of
    // series or a reload, since each chart's frame reads it here.
  }
}
