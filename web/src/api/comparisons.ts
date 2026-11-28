import { queryOptions } from "@tanstack/react-query"
import { api } from "./client"
import { answer } from "./problems"
import type { components } from "./schema"

/** Two to four saved runs side by side, the first the reference (step 5.10). */
export type RunComparison = components["schemas"]["RunComparison"]
/** A run of a comparison: its figures, what they differ by from the reference's, its trades by
 * exit reason, and its equity over its capital. */
export type ComparedRun = components["schemas"]["ComparedRun"]
/** A run's figures as its KPI cards show them, or what they differ by. */
export type RunFigures = components["schemas"]["RunFigures"]
/** A run's equity at each trade date's end over its capital. */
export type ShareCurve = components["schemas"]["ShareCurve"]

/** The comparison of the saved runs `runKeys`, the first the reference (`POST /v1/runs/compare`),
 * kept while the app is open, since a saved run's figures never change. */
export function comparisonQuery(runKeys: readonly string[]) {
  return queryOptions({
    queryKey: ["run-comparison", ...runKeys],
    queryFn: async () =>
      answer(
        await api.POST("/v1/runs/compare", { body: { runs: [...runKeys] } })
      ),
    staleTime: Infinity,
    gcTime: Infinity,
  })
}
