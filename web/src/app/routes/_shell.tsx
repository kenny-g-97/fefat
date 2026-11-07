import { createFileRoute, redirect } from "@tanstack/react-router"
import { identityQuery } from "@/api/client"
import { isRefusal } from "@/api/problems"
import { settingsQuery } from "@/api/settings"
import { ErrorPage } from "../ErrorPage"
import { Shell } from "../shell/Shell"
import { StandalonePage } from "../StandalonePage"

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
  // The shell's own failure, its identity check or its settings, has no sidebar to stand in.
  errorComponent: (props) => (
    <StandalonePage>
      <ErrorPage {...props} />
    </StandalonePage>
  ),
})
