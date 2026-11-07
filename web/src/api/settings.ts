import { queryOptions, useMutation } from "@tanstack/react-query"
import { api, queryClient } from "./client"
import { answer } from "./problems"
import type { components } from "./schema"

export type Theme = components["schemas"]["Theme"]

/** The settings page's settings: the server's, the data folder, the theme, and whether each
 * secret is stored. */
export const settingsQuery = queryOptions({
  queryKey: ["settings"],
  queryFn: async () => answer(await api.GET("/v1/settings")),
})

/** Keep `theme` as the theme, which the server's database holds for every browser. */
export function useThemeChange() {
  return useMutation({
    mutationFn: async (theme: Theme) =>
      answer(await api.PUT("/v1/settings", { body: { theme } })),
    onSuccess: (settings) =>
      queryClient.setQueryData(settingsQuery.queryKey, settings),
  })
}
