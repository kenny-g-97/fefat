import { createFileRoute } from "@tanstack/react-router"
import { z } from "zod"
import { LoginPage } from "../login/LoginPage"

// The page the login returns to: a path of this app alone, never `//another.site`.
const search = z.object({
  redirect: z
    .string()
    .regex(/^\/(?![/\\])/)
    .optional()
    .catch(undefined),
})

export const Route = createFileRoute("/login")({
  validateSearch: search,
  component: LoginRoute,
})

function LoginRoute() {
  const { redirect } = Route.useSearch()
  return <LoginPage returnTo={redirect ?? "/"} />
}
