import { QueryClient, queryOptions } from "@tanstack/react-query"
import createClient from "openapi-fetch"
import { answer } from "./problems"
import type { paths } from "./schema"

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"])
const CSRF_HEADER = "X-CSRF-Token"
const LOGIN = "/v1/auth/login"

/** The one cache of what the server answered, which the router's loaders and the pages
 * share. */
export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

/** The typed client of the local server's API, generated from `web/openapi.json`. */
export const api = createClient<paths>()

/** Who the browser is logged in as, with the session's CSRF token; asked again at every
 * navigation into the app, so that a session that ended leads back to the login. */
export const identityQuery = queryOptions({
  queryKey: ["identity"],
  queryFn: async () => answer(await api.GET("/v1/me")),
  staleTime: 0,
})

api.use({
  // A change of state carries the CSRF token of the session the cookie holds now, asked afresh,
  // since a login or a password change in another tab replaces the session.
  async onRequest({ request, schemaPath }) {
    if (SAFE_METHODS.has(request.method) || schemaPath === LOGIN) {
      return request
    }
    const identity = await queryClient.fetchQuery(identityQuery)
    if (identity.kind === "session") {
      request.headers.set(CSRF_HEADER, identity.csrf_token)
    }
    return request
  },
  onError() {
    return new Error("The server did not answer: is fefat up still running?")
  },
})
