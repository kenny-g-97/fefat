import { useSyncExternalStore } from "react"

/** The padding a page ends with under its content (web/DESIGN.md, Layout, Measures). */
const PAGE_PADDING = 32

/** Whether some of the page's content lies under the window's foot, as in a window shorter than
 * a chart's page, or under a chart the trader made taller than the window: then the wheel
 * scrolls the page rather than zooming the chart, so that the page never traps the wheel. A
 * page longer than the window by no more than its own padding hides none of its content, and
 * leaves the wheel to the chart. */
export function usePageScrolls(): boolean {
  return useSyncExternalStore(onLayout, pageScrolls)
}

function onLayout(changed: () => void): () => void {
  const observer = new ResizeObserver(changed)
  observer.observe(document.body)
  window.addEventListener("resize", changed)
  return () => {
    observer.disconnect()
    window.removeEventListener("resize", changed)
  }
}

function pageScrolls(): boolean {
  const root = document.documentElement
  return root.scrollHeight - root.clientHeight > PAGE_PADDING
}
