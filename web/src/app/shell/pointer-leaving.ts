import { type RefObject, useEffect } from "react"

/** Calls `left`, while `watching`, at the pointer's first move outside `element`: the browser's
 * own leave event is lost when the element under the pointer is removed, as a Cancel button is
 * once its job ends, which would leave the jobs drawer's rows held for good. */
export function usePointerLeaving(
  watching: boolean,
  element: RefObject<Element | null>,
  left: () => void
): void {
  useEffect(() => {
    if (!watching) {
      return
    }
    const moved = (event: PointerEvent) => {
      const within =
        event.target instanceof Node &&
        element.current?.contains(event.target) === true
      if (!within) {
        left()
      }
    }
    document.addEventListener("pointermove", moved)
    return () => document.removeEventListener("pointermove", moved)
  }, [watching, element, left])
}
