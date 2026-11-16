import { useEffect } from "react"

/** Keep a file dropped beside a drop target from opening in the tab in the page's place, as the
 * browser would by default, losing what the page held (web/DESIGN.md, Patterns, File drop): a
 * drag over the page outside a target shows that nothing drops there, and its drop does
 * nothing. A target's own handlers take its drops first, which this leaves alone. */
export function useStrayDropsIgnored() {
  useEffect(() => {
    const ignored = (event: DragEvent) => {
      if (event.defaultPrevented) {
        return
      }
      event.preventDefault()
      if (event.dataTransfer !== null) {
        event.dataTransfer.dropEffect = "none"
      }
    }
    window.addEventListener("dragover", ignored)
    window.addEventListener("drop", ignored)
    return () => {
      window.removeEventListener("dragover", ignored)
      window.removeEventListener("drop", ignored)
    }
  }, [])
}
