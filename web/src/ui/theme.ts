import { useSyncExternalStore } from "react"
import type { Theme } from "@/api/settings"

const CROSS_FADE_MS = 200
let fading: number | undefined

function isShown(theme: Theme) {
  return (
    document.documentElement.classList.contains("dark") === (theme === "dark")
  )
}

/** The theme the page shows now, the class on the root element, which a canvas that paints
 * its own colours, such as a chart's, follows; the specs switch it there too. */
export function useShownTheme(): Theme {
  return useSyncExternalStore(onThemeShown, shownTheme)
}

function onThemeShown(changed: () => void): () => void {
  const observer = new MutationObserver(changed)
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  })
  return () => observer.disconnect()
}

function shownTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light"
}

/** Paint `theme` at once, as the class `dark` on the root element that web/DESIGN.md's tokens
 * follow, with every transition off: a theme painted on load moves nothing (the design
 * brief's motion floor). */
export function showTheme(theme: Theme) {
  if (isShown(theme)) {
    return
  }
  const root = document.documentElement
  root.classList.add("theme-instant")
  root.classList.toggle("dark", theme === "dark")
  // Laying the page out now applies the new colours while the transitions are still off.
  document.body.getBoundingClientRect()
  root.classList.remove("theme-instant")
}

/** Switch to `theme` with the cross-fade that answers the trader's own choice (web/DESIGN.md,
 * Motion); a second switch within the fade restarts its timer rather than cutting it short. */
export function switchTheme(theme: Theme) {
  if (isShown(theme)) {
    return
  }
  const root = document.documentElement
  window.clearTimeout(fading)
  root.classList.add("theme-changing")
  root.classList.toggle("dark", theme === "dark")
  fading = window.setTimeout(
    () => root.classList.remove("theme-changing"),
    CROSS_FADE_MS
  )
}
