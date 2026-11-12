import { queryOptions, useMutation } from "@tanstack/react-query"
import { api, queryClient } from "./client"
import { answer } from "./problems"
import type { components } from "./schema"

export type Theme = components["schemas"]["Theme"]

/** The charts' style the trader chose, which every chart and browser draws with. */
export type ChartStyle = components["schemas"]["ChartStyle"]

/** The settings page's settings: the server's, the data folder, the theme, the charts' style,
 * and whether each secret is stored. */
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

/** Draw every chart with `style` at once, before the server keeps it, as a colour field does
 * while its picker is dragged. */
export function previewChartStyle(style: ChartStyle): void {
  queryClient.setQueryData(settingsQuery.queryKey, (settings) =>
    settings === undefined ? settings : { ...settings, chart_style: style }
  )
}

/** Keep `style` as the charts' style, which the server's database holds for every chart and
 * browser; drawn at once, and the server's own read again where it refuses. */
export function useChartStyleChange() {
  return useMutation({
    mutationFn: async (style: ChartStyle) =>
      answer(await api.PUT("/v1/settings", { body: { chart_style: style } })),
    onMutate: (style) => previewChartStyle(style),
    onSuccess: (settings) =>
      queryClient.setQueryData(settingsQuery.queryKey, settings),
    onError: () =>
      queryClient.invalidateQueries({ queryKey: settingsQuery.queryKey }),
  })
}
