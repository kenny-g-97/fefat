/** A frame's size as the trader set it: a width and a height in pixels, each null while the
 * frame fills what its page leaves it. */
export type FrameSize = Readonly<{
  width: number | null
  height: number | null
}>

/** A frame as it is drawn, in pixels. */
export type FrameBox = Readonly<{ width: number; height: number }>

/** The sizes a frame may take: its least, its most height, and its most width, its column's. */
export type FrameLimits = Readonly<{
  leastWidth: number
  leastHeight: number
  mostWidth: number
  mostHeight: number
}>

/** What of a frame a pointer drags: its right edge, its bottom edge, or the corner between. */
export type FrameGrip = "right" | "bottom" | "corner"

/** A frame that fills what its page leaves it, in both directions. */
export const FILLS: FrameSize = { width: null, height: null }

const FILLS_WITHIN = 8
const KEY_STEP = 16
const WIDTH_STEPS: Readonly<Record<string, number>> = {
  ArrowLeft: -KEY_STEP,
  ArrowRight: KEY_STEP,
}
const HEIGHT_STEPS: Readonly<Record<string, number>> = {
  ArrowUp: -KEY_STEP,
  ArrowDown: KEY_STEP,
}

/** The size of a frame whose `grip` a pointer moved by `moved` since the drag began, when it
 * was `size` and drawn as `start`: the right edge sets the width, the bottom edge the height,
 * and the corner both, each within `limits`. A press alone pins no size, and an edge brought
 * back to where the drag began gives the size the frame had. */
export function draggedSize(
  size: FrameSize,
  grip: FrameGrip,
  start: FrameBox,
  moved: Readonly<{ dx: number; dy: number }>,
  limits: FrameLimits
): FrameSize {
  const width = Math.floor(start.width) + Math.round(moved.dx)
  const height = Math.floor(start.height) + Math.round(moved.dy)
  return {
    width:
      grip === "bottom"
        ? size.width
        : widthAfter(size.width, start.width, width, limits),
    height:
      grip === "right"
        ? size.height
        : heightAfter(size.height, start.height, height, limits),
  }
}

/** The size of a frame that is `size` and drawn as `drawn` after `key` on one of its edges: the
 * arrows along the edge's direction move it 16 px, Home and End go to the least and the most,
 * and Enter fills again; undefined for a key that is not the edge's, which the page keeps. */
export function keyedSize(
  size: FrameSize,
  edge: "right" | "bottom",
  key: string,
  drawn: FrameBox,
  limits: FrameLimits
): FrameSize | undefined {
  if (edge === "right") {
    const width = keyed(key, WIDTH_STEPS, drawn.width, {
      least: limits.leastWidth,
      most: limits.mostWidth,
    })
    if (width === undefined) {
      return undefined
    }
    return {
      ...size,
      width:
        width === null
          ? null
          : widthAfter(size.width, drawn.width, width, limits),
    }
  }
  const height = keyed(key, HEIGHT_STEPS, drawn.height, {
    least: limits.leastHeight,
    most: limits.mostHeight,
  })
  if (height === undefined) {
    return undefined
  }
  return {
    ...size,
    height:
      height === null
        ? null
        : heightAfter(size.height, drawn.height, height, limits),
  }
}

/** Where `key` takes an edge drawn at `now`: a length in pixels, null to fill again, or
 * undefined for a key that moves nothing. */
function keyed(
  key: string,
  steps: Readonly<Record<string, number>>,
  now: number,
  ends: Readonly<{ least: number; most: number }>
): number | null | undefined {
  if (key === "Enter") {
    return null
  }
  if (key === "Home") {
    return ends.least
  }
  if (key === "End") {
    return ends.most
  }
  const step = steps[key]
  return step === undefined ? undefined : Math.floor(now) + step
}

/** The width of a frame that `was` so wide and is drawn `drawn` px wide, after a move that asks
 * for `asked`: as it was where the edge would stand where it is drawn, at its least or at its
 * column, since a move that shows nothing changes nothing, be the frame filling or set; null,
 * the column's own, from 8 px under the most, so that a frame dragged back to its column fills
 * it again and narrows with it; else `asked`, never under the least. */
function widthAfter(
  was: number | null,
  drawn: number,
  asked: number,
  limits: FrameLimits
): number | null {
  const within = Math.min(limits.mostWidth, Math.max(limits.leastWidth, asked))
  if (within === Math.floor(drawn)) {
    return was
  }
  return within >= limits.mostWidth - FILLS_WITHIN ? null : within
}

/** The height after such a move: as it `was` where the edge would stand where it is drawn,
 * and, for a frame that fills, until its edge has moved more than 8 px, so that a corner
 * pulled sideways pins no height; else `asked`, within the least and the most. */
function heightAfter(
  was: number | null,
  drawn: number,
  asked: number,
  limits: FrameLimits
): number | null {
  const within = Math.min(
    limits.mostHeight,
    Math.max(limits.leastHeight, asked)
  )
  const moved = Math.abs(within - Math.floor(drawn))
  return moved === 0 || (was === null && moved <= FILLS_WITHIN) ? was : within
}
