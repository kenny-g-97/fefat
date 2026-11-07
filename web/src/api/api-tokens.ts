import { queryOptions, useMutation } from "@tanstack/react-query"
import { api, queryClient } from "./client"
import { answer, succeeded } from "./problems"

/** The API tokens not revoked, by their names and times, never a token. */
export const apiTokensQuery = queryOptions({
  queryKey: ["api-tokens"],
  queryFn: async () => answer(await api.GET("/v1/api-tokens")),
})

/** Make an API token named as given, which the answer alone carries. */
export function useTokenCreation() {
  return useMutation({
    mutationFn: async (name: string) =>
      answer(await api.POST("/v1/api-tokens", { body: { name } })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: apiTokensQuery.queryKey }),
  })
}

/** Revoke the API token of the given name, which every request refuses from then on. */
export function useTokenRevocation() {
  return useMutation({
    mutationFn: async (name: string) =>
      succeeded(
        await api.DELETE("/v1/api-tokens/{name}", {
          params: { path: { name } },
        })
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: apiTokensQuery.queryKey }),
  })
}
