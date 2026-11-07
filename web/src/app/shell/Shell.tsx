import { useSuspenseQuery } from "@tanstack/react-query"
import { Outlet } from "@tanstack/react-router"
import { useLayoutEffect, useRef } from "react"
import { settingsQuery } from "@/api/settings"
import { showTheme, switchTheme } from "@/ui/theme"
import { Sidebar } from "./Sidebar"

/** The app behind the login: the sidebar beside the page, in the theme the server keeps,
 * painted at once before the first frame, and with the cross-fade when the trader changes it
 * after that. */
export function Shell() {
  const { data: settings } = useSuspenseQuery(settingsQuery)
  const painted = useRef(false)
  useLayoutEffect(() => {
    if (painted.current) {
      switchTheme(settings.theme)
      return
    }
    painted.current = true
    showTheme(settings.theme)
  }, [settings.theme])
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
