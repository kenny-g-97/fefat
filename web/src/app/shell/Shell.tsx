import { useSuspenseQuery } from "@tanstack/react-query"
import { Outlet } from "@tanstack/react-router"
import { useLayoutEffect, useRef } from "react"
import { settingsQuery } from "@/api/settings"
import { showTheme, switchTheme } from "@/ui/theme"
import { Sidebar } from "./Sidebar"

/** The app behind the login: a skip link past the sidebar, the sidebar beside the page, in the
 * theme the server keeps, painted at once before the first frame, and with the cross-fade when
 * the trader changes it after that. */
export function Shell() {
  const { data: settings } = useSuspenseQuery(settingsQuery)
  const painted = useRef(false)
  const main = useRef<HTMLElement>(null)
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
      <a
        href="#main"
        onClick={(event) => {
          event.preventDefault()
          main.current?.focus()
        }}
        className="absolute -top-24 left-4 z-50 rounded-xl border bg-muted px-5 py-3 font-medium shadow-md focus:top-4"
      >
        Skip to content
      </a>
      <Sidebar />
      <main ref={main} id="main" tabIndex={-1} className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
