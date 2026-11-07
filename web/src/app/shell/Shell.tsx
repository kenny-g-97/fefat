import { useSuspenseQuery } from "@tanstack/react-query"
import { Outlet } from "@tanstack/react-router"
import { useLayoutEffect } from "react"
import { settingsQuery } from "@/api/settings"
import { showTheme } from "@/ui/theme"
import { Sidebar } from "./Sidebar"

/** The app behind the login: the sidebar beside the page, in the theme the trader chose,
 * painted before the first frame. */
export function Shell() {
  const { data: settings } = useSuspenseQuery(settingsQuery)
  useLayoutEffect(() => showTheme(settings.theme), [settings.theme])
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
