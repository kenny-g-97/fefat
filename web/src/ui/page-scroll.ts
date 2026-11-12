import { useSyncExternalStore } from "react"

/** Whether the page is taller than the window, and so scrolls, as a window shorter than a
 * chart's page does: then the wheel scrolls the page rather than zooming the chart, so that
 * the page never traps the wheel. */
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
  return root.scrollHeight > root.clientHeight
}
