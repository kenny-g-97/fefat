import { createFileRoute, redirect } from "@tanstack/react-router"
import { identityQuery } from "@/api/client"
import { isRefusal } from "@/api/problems"
import { settingsQuery } from "@/api/settings"
import { Shell } from "../shell/Shell"

// Every page behind the login: the server is asked who the browser is at each navigation, and
// a browser without a live session goes to the login, which returns it here.
export const Route = createFileRoute("/_shell")({
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.fetchQuery(identityQuery)
    } catch (error) {
      if (isRefusal(error, 401)) {
        throw redirect({ to: "/login", search: { redirect: location.href } })
      }
      throw error
    }
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(settingsQuery),
  component: Shell,
})
