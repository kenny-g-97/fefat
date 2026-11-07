import type { Theme } from "@/api/settings"

const CROSS_FADE_MS = 200

function isShown(theme: Theme) {
  return (
    document.documentElement.classList.contains("dark") === (theme === "dark")
  )
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
 * Motion). */
export function switchTheme(theme: Theme) {
  if (isShown(theme)) {
    return
  }
  const root = document.documentElement
  root.classList.add("theme-changing")
  root.classList.toggle("dark", theme === "dark")
  window.setTimeout(
    () => root.classList.remove("theme-changing"),
    CROSS_FADE_MS
  )
}
