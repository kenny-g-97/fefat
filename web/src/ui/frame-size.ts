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
 * was drawn as `start`: the right edge sets the width, the bottom edge the height, and the
 * corner both, each within `limits`. A dimension the pointer has not moved stays as it was, so
 * that a press alone pins no size. */
export function draggedSize(
  size: FrameSize,
  grip: FrameGrip,
  start: FrameBox,
  moved: Readonly<{ dx: number; dy: number }>,
  limits: FrameLimits
): FrameSize {
  const width =
    grip === "bottom" || moved.dx === 0
      ? size.width
      : widthWithin(Math.floor(start.width) + Math.round(moved.dx), limits)
  const height =
    grip === "right" || moved.dy === 0
      ? size.height
      : heightWithin(Math.floor(start.height) + Math.round(moved.dy), limits)
  return { width, height }
}

/** The size of a frame drawn as `drawn` after `key` on one of its edges: the arrows along the
 * edge's direction move it 16 px, Home and End go to the least and the most, and Enter fills
 * again; undefined for a key that is not the edge's, which the page keeps. */
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
    return width === undefined
      ? undefined
      : { ...size, width: width === null ? null : widthWithin(width, limits) }
  }
  const height = keyed(key, HEIGHT_STEPS, drawn.height, {
    least: limits.leastHeight,
    most: limits.mostHeight,
  })
  return height === undefined
    ? undefined
    : { ...size, height: height === null ? null : heightWithin(height, limits) }
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

/** A width within the limits: null, the column's own, from 8 px under the most, so that a
 * frame dragged back to its column fills it again and narrows with it. */
function widthWithin(width: number, limits: FrameLimits): number | null {
  if (width >= limits.mostWidth - FILLS_WITHIN) {
    return null
  }
  return Math.max(limits.leastWidth, width)
}

function heightWithin(height: number, limits: FrameLimits): number {
  return Math.min(limits.mostHeight, Math.max(limits.leastHeight, height))
}
