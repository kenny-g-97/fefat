import { useState } from "react"
import { z } from "zod"
import type { FrameSize } from "./frame-size"

/** The least a chart's frame may be, where the readout and the candles still read, and the most
 * it may be tall in a window no taller than that; its most width is its column's. */
export const CHART_FRAME: Readonly<{
  leastWidth: number
  leastHeight: number
  mostHeight: number
}> = {
  leastWidth: 576,
  leastHeight: 240,
  mostHeight: 1600,
}

const keptSize = z.object({
  width: z.number().int().min(CHART_FRAME.leastWidth).nullable(),
  height: z.number().int().min(CHART_FRAME.leastHeight).nullable(),
})

/** The size `text` holds, as the browser's local storage kept it; `fallback`, the size the
 * chart's page gives its frame, where nothing is kept, or where what is kept is no size of the
 * chart's: the storage is the trader's to edit, and another version's to have written. A size
 * past the frame's most is a size still, wider than the column or taller than this window
 * allows, and the frame draws it at its most. */
export function storedFrameSize(
  text: string | null,
  fallback: FrameSize
): FrameSize {
  const read = keptSize.safeParse(text === null ? null : parsed(text))
  return read.success ? read.data : fallback
}

/** The size the trader gave a chart's frame, kept in this browser's local storage under
 * `keptAs`, or else `fallback`, and the way to change it. A size in pixels suits one screen, so
 * it is the browser's, and it is read where the frame is drawn, so that another timeframe's
 * chart stands in the frame as the trader left it (step 5.4); the chart viewer's and the trade
 * review's are kept apart (step 5.9). */
export function useChartFrameSize(
  keptAs: string,
  fallback: FrameSize
): readonly [FrameSize, (size: FrameSize) => void] {
  const [size, setSize] = useState(() => keptFrameSize(keptAs, fallback))
  const resize = (next: FrameSize) => {
    setSize(next)
    // shortcut: written at every move of a drag, a few bytes some hundred times a second;
    // write once as the drag ends if a profile ever shows it.
    keep(keptAs, next)
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

function keptFrameSize(keptAs: string, fallback: FrameSize): FrameSize {
  try {
    return storedFrameSize(localStorage.getItem(keptAs), fallback)
  } catch {
    // A browser that refuses its storage, as a private window may, keeps nothing.
    return fallback
  }
}

function keep(keptAs: string, size: FrameSize): void {
  try {
    localStorage.setItem(keptAs, JSON.stringify(size))
  } catch {
    // Storage refused or full: the size holds until another chart is drawn, by a change of
    // series or a reload, since each chart's frame reads it here.
  }
}
