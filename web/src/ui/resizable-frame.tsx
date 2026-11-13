import { cn } from "cn"
import {
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react"
import {
  draggedSize,
  FILLS,
  type FrameBox,
  type FrameGrip,
  type FrameLimits,
  type FrameSize,
  keyedSize,
} from "./frame-size"

type ResizableFrameProps = Readonly<{
  label: string
  size: FrameSize
  onResize: (size: FrameSize) => void
  leastWidth: number
  leastHeight: number
  mostHeight: number
  children: ReactNode
}>

/** The frame as it is drawn, and the width of the column it stands in, its most. */
type Drawn = FrameBox & Readonly<{ column: number }>

type Drag = Readonly<{
  grip: FrameGrip
  x: number
  y: number
  start: FrameBox
  size: FrameSize
  limits: FrameLimits
}>

const HOW =
  "Drag or press the arrow keys to resize. Double-click or press Enter to fill the page again."
const EDGE =
  "absolute z-10 touch-none rounded-xl select-none after:absolute after:rounded-xl hover:after:bg-brand focus-visible:after:bg-brand active:after:bg-brand"

/** A frame the trader sizes by its edges (web/DESIGN.md, Patterns, Resizable frame): it fills
 * what its page leaves until its right edge, its bottom edge, or the corner between is dragged,
 * then keeps that width, that height, or both, never under its least, over its most height, or
 * wider than its column. The edges are separators named for `label`, after the frame's content
 * in the page, which the arrows, Home, End, and Enter move too; a double click fills again. The
 * handles stand outside the content, so that a card inside may clip its own. */
export function ResizableFrame({
  label,
  size,
  onResize,
  leastWidth,
  leastHeight,
  mostHeight,
  children,
}: ResizableFrameProps) {
  const frame = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const drawn = useDrawn(frame)
  const framed = useId()
  const limitsOf = (now: Drawn): FrameLimits => ({
    leastWidth,
    leastHeight,
    mostWidth: now.column,
    mostHeight,
  })

  // A drag and a key start from the frame as it is drawn at that moment: the box the observer
  // last reported is a frame behind a key pressed twice.
  const pressed =
    (grip: FrameGrip) => (event: PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0 || frame.current === null) {
        return
      }
      event.currentTarget.setPointerCapture(event.pointerId)
      const now = measured(frame.current)
      drag.current = {
        grip,
        x: event.clientX,
        y: event.clientY,
        start: now,
        size,
        limits: limitsOf(now),
      }
    }
  const moved = (event: PointerEvent<HTMLDivElement>) => {
    const from = drag.current
    if (from === null) {
      return
    }
    const by = { dx: event.clientX - from.x, dy: event.clientY - from.y }
    onResize(draggedSize(from.size, from.grip, from.start, by, from.limits))
  }
  const released = () => {
    drag.current = null
  }
  const keyed =
    (edge: "right" | "bottom") => (event: KeyboardEvent<HTMLDivElement>) => {
      if (frame.current === null) {
        return
      }
      const now = measured(frame.current)
      const next = keyedSize(size, edge, event.key, now, limitsOf(now))
      if (next !== undefined) {
        event.preventDefault()
        onResize(next)
      }
    }
  const grips = (grip: FrameGrip, filled: FrameSize) => ({
    onPointerDown: pressed(grip),
    onPointerMove: moved,
    onLostPointerCapture: released,
    onDoubleClick: () => onResize(filled),
  })

  return (
    <div
      ref={frame}
      id={framed}
      className={cn(
        "relative isolate flex max-w-full flex-col",
        size.height === null ? "min-h-0 flex-1" : "shrink-0"
      )}
      style={{
        width: size.width === null ? undefined : size.width,
        height: size.height === null ? undefined : size.height,
      }}
    >
      {children}
      <div
        role="separator"
        tabIndex={0}
        aria-orientation="vertical"
        aria-label={`${label} width`}
        aria-controls={framed}
        aria-valuemin={leastWidth}
        aria-valuemax={drawn.column}
        aria-valuenow={drawn.width}
        aria-valuetext={`${drawn.width} pixels`}
        title={HOW}
        onKeyDown={keyed("right")}
        {...grips("right", { ...size, width: null })}
        className={cn(
          EDGE,
          "top-3 -right-2 bottom-4 w-2 cursor-ew-resize after:inset-y-0 after:left-0 after:w-0.5"
        )}
      />
      <div
        role="separator"
        tabIndex={0}
        aria-orientation="horizontal"
        aria-label={`${label} height`}
        aria-controls={framed}
        aria-valuemin={leastHeight}
        aria-valuemax={mostHeight}
        aria-valuenow={drawn.height}
        aria-valuetext={`${drawn.height} pixels`}
        title={HOW}
        onKeyDown={keyed("bottom")}
        {...grips("bottom", { ...size, height: null })}
        className={cn(
          EDGE,
          "right-4 -bottom-2 left-3 h-2 cursor-ns-resize after:inset-x-0 after:top-0 after:h-0.5"
        )}
      />
      <div
        aria-hidden="true"
        data-testid="frame-corner"
        {...grips("corner", FILLS)}
        className="absolute right-0 bottom-0 z-10 size-4 cursor-nwse-resize touch-none text-muted-foreground select-none"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor">
          <path d="M12 7 7 12M12 10.5 10.5 12" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  )
}

/** `frame` as it is drawn now, and the width its column leaves it, in whole pixels. */
function measured(frame: HTMLElement): Drawn {
  const column = frame.parentElement
  if (column === null) {
    throw new Error("Expected the frame in a column of its page, got none.")
  }
  const box = frame.getBoundingClientRect()
  const around = getComputedStyle(column)
  return {
    width: Math.floor(box.width),
    height: Math.floor(box.height),
    column: Math.floor(
      column.clientWidth -
        parseFloat(around.paddingLeft) -
        parseFloat(around.paddingRight)
    ),
  }
}

/** The frame's box and its column's width, kept as either changes: what the edges say of
 * themselves to a screen reader. */
function useDrawn(frame: Readonly<{ current: HTMLDivElement | null }>): Drawn {
  const [drawn, setDrawn] = useState<Drawn>({ width: 0, height: 0, column: 0 })
  useEffect(() => {
    const element = frame.current
    if (element === null || element.parentElement === null) {
      return
    }
    const sizes = new ResizeObserver(() => setDrawn(measured(element)))
    sizes.observe(element)
    sizes.observe(element.parentElement)
    return () => sizes.disconnect()
  }, [frame])
  return drawn
}
