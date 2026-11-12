import { queryOptions, useMutation } from "@tanstack/react-query"
import { api, queryClient } from "./client"
import { answer } from "./problems"
import type { components } from "./schema"

export type Theme = components["schemas"]["Theme"]

/** The charts' style the trader chose, which every chart and browser draws with. */
export type ChartStyle = components["schemas"]["ChartStyle"]

const THEMES_OWN = {
  up: null,
  down: null,
  background: null,
  grid: null,
  text: null,
}

/** FEAT's own chart style, the defaults of `fefat_app.chart_style.ChartStyle`: hollow candles in
 * the theme's sign colours, the volume, the grid, and the sessions' shading shown. */
export const FEATS_CHART_STYLE: ChartStyle = {
  up_body: "hollow",
  down_body: "hollow",
  volume_shown: true,
  volume_colouring: "neutral",
  grid_shown: true,
  sessions_shaded: true,
  dark: THEMES_OWN,
  light: THEMES_OWN,
}

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

/** A change to the charts' style: the style it makes of the one drawn when it is made. */
export type ChartStyleChange = (drawn: ChartStyle) => ChartStyle

const CHART_STYLE_KEPT = ["settings", "chart_style"]

/** Draw every chart with `change` made at once, before the server keeps it, as a colour field
 * does while its picker is dragged. */
export function previewChartStyle(change: ChartStyleChange): void {
  queryClient.setQueryData(settingsQuery.queryKey, (settings) =>
    settings === undefined
      ? settings
      : { ...settings, chart_style: change(settings.chart_style) }
  )
}

/** Keep each change to the charts' style, which the server's database holds for every chart and
 * browser: made to the style drawn at that moment and drawn at once, and sent one after another
 * in the order made, so that changes in quick succession all stay; the server's answer is drawn
 * once no later change is on its way, and the server's own style read again where it refuses
 * (TanStack's concurrent optimistic updates, in one mutation scope). */
export function useChartStyleChange() {
  const mutation = useMutation({
    mutationKey: CHART_STYLE_KEPT,
    scope: { id: "chart_style" },
    mutationFn: async (style: ChartStyle) =>
      answer(await api.PUT("/v1/settings", { body: { chart_style: style } })),
    onMutate: async (style) => {
      await queryClient.cancelQueries({ queryKey: settingsQuery.queryKey })
      previewChartStyle(() => style)
    },
    onSuccess: (settings) => {
      if (queryClient.isMutating({ mutationKey: CHART_STYLE_KEPT }) === 1) {
        queryClient.setQueryData(settingsQuery.queryKey, settings)
      }
    },
    onError: () =>
      queryClient.invalidateQueries({ queryKey: settingsQuery.queryKey }),
  })
  return {
    keep: (change: ChartStyleChange) =>
      mutation.mutate(change(drawnChartStyle())),
    error: mutation.error,
  }
}

function drawnChartStyle(): ChartStyle {
  const settings = queryClient.getQueryData(settingsQuery.queryKey)
  if (settings === undefined) {
    throw new Error(
      "Expected the settings read before the charts' style changes, got none."
    )
  }
  return settings.chart_style
}
