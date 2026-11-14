import { cn } from "cn"
import {
  type KeyboardEvent,
  type MouseEvent,
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

/** The frame as it is drawn, the width of the column it stands in, its most, and the most it
 * may be tall in the window as it is. */
type Drawn = FrameBox & Readonly<{ column: number; most: number }>

type Drag = Readonly<{
  grip: FrameGrip
  x: number
  y: number
  start: FrameBox
  size: FrameSize
}>

const HOW_BY_THE_POINTER =
  "Drag to resize. Double-click to fill the page again."
const HOW_BY_THE_KEYS =
  "Press the arrow keys to resize. Press Enter to fill the page again."
const EDGE =
  "absolute z-10 touch-none rounded-xl select-none after:absolute after:rounded-xl hover:after:bg-brand focus-visible:after:bg-brand active:after:bg-brand"

/** A frame the trader sizes by its edges (web/DESIGN.md, Patterns, Resizable frame): it fills
 * what its page leaves until its right edge, its bottom edge, or the corner between is dragged,
 * then keeps that width, that height, or both, never under its least, wider than its column, or
 * taller than its most, which is the window's height where that is more. The edges are
 * separators named for `label`, after the frame's content in the page, which the arrows, Home,
 * End, and Enter move too; a double click fills again. Each handle's tooltip is the pointer's
 * way, and the edges' description, for who Tabs to them, the keys'. The handles are the
 * content's siblings,
 * so that a card inside may clip its own, and each edge's strip lies over the card's last 2 px,
 * its hairline, and 6 px outside it: a pointer aiming at the edge it sees grabs the frame, not
 * what the card draws beside it. */
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
  const drawn = useDrawn(frame, mostHeight)
  const framed = useId()
  const byTheKeys = useId()
  const limitsOf = (now: Drawn): FrameLimits => ({
    leastWidth,
    leastHeight,
    mostWidth: now.column,
    mostHeight: now.most,
  })

  // A drag and a key start from the frame as it is drawn at that moment: the box the observer
  // last reported is a frame behind a key pressed twice.
  const pressed =
    (grip: FrameGrip) => (event: PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0 || frame.current === null) {
        return
      }
      event.currentTarget.setPointerCapture(event.pointerId)
      drag.current = {
        grip,
        x: event.clientX,
        y: event.clientY,
        start: measured(frame.current, mostHeight),
        size,
      }
    }
  // The pointer's own move since the press sizes the frame, in the window's coordinates: the
  // page's would count the scroll the browser makes by itself when a shrinking frame shortens
  // a page scrolled to its end, and each move would then shrink the frame further. The limits
  // are this move's, since the column narrows under the scrollbar a taller frame brings.
  const moved = (event: PointerEvent<HTMLDivElement>) => {
    const from = drag.current
    if (from === null || frame.current === null) {
      return
    }
    const by = { dx: event.clientX - from.x, dy: event.clientY - from.y }
    const limits = limitsOf(measured(frame.current, mostHeight))
    onResize(draggedSize(from.size, from.grip, from.start, by, limits))
  }
  const released = () => {
    drag.current = null
  }
  const keyed =
    (edge: "right" | "bottom") => (event: KeyboardEvent<HTMLDivElement>) => {
      if (frame.current === null) {
        return
      }
      const now = measured(frame.current, mostHeight)
      const next = keyedSize(size, edge, event.key, now, limitsOf(now))
      if (next === undefined) {
        return
      }
      event.preventDefault()
      onResize(next)
      if (edge === "bottom") {
        // The edge the keys hold stays in view as its frame grows past the window's foot.
        const held = event.currentTarget
        requestAnimationFrame(() => held.scrollIntoView({ block: "nearest" }))
      }
    }
  const grips = (grip: FrameGrip, filled: FrameSize) => ({
    onPointerDown: pressed(grip),
    onPointerMove: moved,
    onLostPointerCapture: released,
    onDoubleClick: () => onResize(filled),
    // A press of the pointer leaves the focus where it was: an edge that held it unseen would
    // take the keys of what it frames, a chart's End among them, and size the frame.
    onMouseDown: (event: MouseEvent<HTMLDivElement>) => event.preventDefault(),
  })

  return (
    <div
      ref={frame}
      id={framed}
      className={cn(
        "relative isolate flex max-w-full flex-col",
        size.height === null ? "flex-1" : "shrink-0"
      )}
      style={{
        width: size.width === null ? undefined : size.width,
        height: size.height === null ? undefined : size.height,
        minHeight: leastHeight,
        maxHeight: `max(${mostHeight}px, 100dvh)`,
      }}
    >
      {children}
      <span id={byTheKeys} hidden>
        {HOW_BY_THE_KEYS}
      </span>
      <div
        role="separator"
        tabIndex={0}
        aria-orientation="vertical"
        aria-label={`${label} width`}
        aria-describedby={byTheKeys}
        aria-controls={framed}
        aria-valuemin={leastWidth}
        aria-valuemax={drawn.column}
        aria-valuenow={drawn.width}
        aria-valuetext={`${drawn.width} pixels`}
        title={HOW_BY_THE_POINTER}
        data-slot="frame-edge"
        onKeyDown={keyed("right")}
        {...grips("right", { ...size, width: null })}
        className={cn(
          EDGE,
          "top-3 -right-1.5 bottom-4 w-2 cursor-ew-resize after:inset-y-0 after:left-0 after:w-0.5"
        )}
      />
      <div
        role="separator"
        tabIndex={0}
        aria-orientation="horizontal"
        aria-label={`${label} height`}
        aria-describedby={byTheKeys}
        aria-controls={framed}
        aria-valuemin={leastHeight}
        aria-valuemax={drawn.most}
        aria-valuenow={drawn.height}
        aria-valuetext={`${drawn.height} pixels`}
        title={HOW_BY_THE_POINTER}
        data-slot="frame-edge"
        onKeyDown={keyed("bottom")}
        {...grips("bottom", { ...size, height: null })}
        className={cn(
          EDGE,
          "right-4 -bottom-1.5 left-3 h-2 scroll-mb-8 cursor-ns-resize after:inset-x-0 after:top-0 after:h-0.5"
        )}
      />
      <div
        aria-hidden="true"
        data-testid="frame-corner"
        title={HOW_BY_THE_POINTER}
        {...grips("corner", FILLS)}
        className="absolute -right-1.5 -bottom-1.5 z-10 size-5.5 cursor-nwse-resize touch-none text-muted-foreground select-none hover:text-brand active:text-brand"
      >
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="size-4"
        >
          <path d="M12.5 5 5 12.5M12.5 9 9 12.5" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  )
}

/** `frame` as it is drawn now and the width its column leaves it, in whole pixels, and the
 * most it may be tall: `mostHeight`, or the window's height where that is more, so that a frame
 * filling a tall window is within its most. */
function measured(frame: HTMLElement, mostHeight: number): Drawn {
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
    most: Math.max(mostHeight, window.innerHeight),
  }
}

/** The frame's box, its column's width, and its most height, kept as its box, its column, or
 * the window changes: what the edges say of themselves to a screen reader. */
function useDrawn(
  frame: Readonly<{ current: HTMLDivElement | null }>,
  mostHeight: number
): Drawn {
  const [drawn, setDrawn] = useState<Drawn>({
    width: 0,
    height: 0,
    column: 0,
    most: mostHeight,
  })
  useEffect(() => {
    const element = frame.current
    if (element === null || element.parentElement === null) {
      return
    }
    const measure = () => setDrawn(measured(element, mostHeight))
    const sizes = new ResizeObserver(measure)
    sizes.observe(element)
    sizes.observe(element.parentElement)
    // The most height is the window's where that is more, and a set frame's box stays as the
    // window grows.
    window.addEventListener("resize", measure)
    return () => {
      sizes.disconnect()
      window.removeEventListener("resize", measure)
    }
  }, [frame, mostHeight])
  return drawn
}
