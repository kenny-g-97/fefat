import { queryOptions, useMutation } from "@tanstack/react-query"
import { api, queryClient } from "./client"
import { answer } from "./problems"
import type { components } from "./schema"

export type IndexedStrategy = components["schemas"]["IndexedStrategy"]
export type IndexedStrategyVersion =
  components["schemas"]["IndexedStrategyVersion"]
export type SavedStrategyVersion = components["schemas"]["SavedStrategyVersion"]
export type StrategyTemplate = components["schemas"]["StrategyTemplate"]
export type LintFinding = components["schemas"]["StrategyLintFinding"]
export type AbandonedMark = components["schemas"]["AbandonedMark"]
/** Validate's verdict on a strategy's code: valid, with what it trades, or refused at a line. */
export type StrategyVerdict =
  | components["schemas"]["ValidStrategy"]
  | components["schemas"]["RefusedCode"]
type NewStrategy = components["schemas"]["NewStrategy"]
type NewVersion = components["schemas"]["NewStrategyVersionRequest"]
/** Where a strategy broke and its lesson, as a mark asks them. */
export type MarkAsked = components["schemas"]["AbandonedMarkRequest"]

/** The saved strategies by name, each with its versions, its abandoned mark, and when it last
 * ran; the server indexes the library first, so a version a notebook saved is listed (step
 * 5.5). */
export const strategiesQuery = queryOptions({
  queryKey: ["strategies"],
  queryFn: async () => answer(await api.GET("/v1/strategies")),
})

/** The strategies to start from, which FEAT ships and no session changes. */
export const strategyTemplatesQuery = queryOptions({
  queryKey: ["strategy-templates"],
  queryFn: async () => answer(await api.GET("/v1/strategies/templates")),
  staleTime: Infinity,
})

/** Version `version` of the strategy `strategyId` as its file keeps it, with the lint's
 * findings in its code; a version never changes, so it is read once. */
export function strategyVersionQuery(strategyId: string, version: number) {
  return queryOptions({
    queryKey: ["strategy-versions", strategyId, version],
    queryFn: async () =>
      answer(
        await api.GET("/v1/strategies/{strategy_id}/versions/{number}", {
          params: { path: { strategy_id: strategyId, number: version } },
        })
      ),
    staleTime: Infinity,
  })
}

/** Build a strategy's code in the server's executor, never in the browser or the server: its
 * verdict, valid or refused at a line. */
export function useStrategyValidation() {
  return useMutation({
    mutationFn: async (code: string) =>
      answer(await api.POST("/v1/strategies/validate", { body: { code } })),
  })
}

/** Create a strategy with its version 1, built and saved in the executor; the list is read again
 * before the caller hears of it, so that the strategy's page finds it. */
export function useStrategyCreation() {
  return useMutation({
    mutationFn: async (asked: NewStrategy) =>
      answer(await api.POST("/v1/strategies", { body: asked })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: strategiesQuery.queryKey }),
  })
}

/** Save the next version of the strategy `strategyId`, or find the same code saved with the same
 * words; the list is read again before the caller hears of it. */
export function useVersionSave(strategyId: string) {
  return useMutation({
    mutationFn: async (asked: NewVersion) =>
      answer(
        await api.POST("/v1/strategies/{strategy_id}/versions", {
          params: { path: { strategy_id: strategyId } },
          body: asked,
        })
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: strategiesQuery.queryKey }),
  })
}

/** Mark the strategy `strategyId` abandoned with where it broke and its lesson (D-29). */
export function useAbandonment(strategyId: string) {
  return useMutation({
    mutationFn: async (mark: MarkAsked) =>
      answer(
        await api.POST("/v1/strategies/{strategy_id}/abandon", {
          params: { path: { strategy_id: strategyId } },
          body: mark,
        })
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: strategiesQuery.queryKey }),
  })
}

/** Take back the abandoned mark of the strategy `strategyId`. */
export function useReopening(strategyId: string) {
  return useMutation({
    mutationFn: async () =>
      answer(
        await api.POST("/v1/strategies/{strategy_id}/reopen", {
          params: { path: { strategy_id: strategyId } },
        })
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: strategiesQuery.queryKey }),
  })
}
