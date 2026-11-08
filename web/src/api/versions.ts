import { queryOptions } from "@tanstack/react-query"
import { api } from "./client"
import { answer } from "./problems"

/** The versions of the app, the SDK, the engine, the fill model, and the artifacts' schema,
 * which a running server never changes. */
export const versionsQuery = queryOptions({
  queryKey: ["versions"],
  queryFn: async () => answer(await api.GET("/v1/version")),
  staleTime: Infinity,
})
