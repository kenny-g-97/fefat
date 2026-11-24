import { queryOptions } from "@tanstack/react-query"
import { api } from "./client"
import { answer } from "./problems"

/** A saved run never changes, so its results are kept for the tab's life, under a key of their
 * own, which the reads after each job's end do not reach. */
const KEPT = { staleTime: Infinity, gcTime: Infinity } as const

async function readStatistics(run: string) {
  return answer(
    await api.GET("/v1/runs/{run}/stats", { params: { path: { run } } })
  )
}

async function readEquity(run: string) {
  return answer(
    await api.GET("/v1/runs/{run}/equity", { params: { path: { run } } })
  )
}

async function readDistributions(run: string) {
  return answer(
    await api.GET("/v1/runs/{run}/distribution", { params: { path: { run } } })
  )
}

/** What a saved run's record says of how it went, as the client reads it. */
export type RunStatistics = Awaited<ReturnType<typeof readStatistics>>
/** A saved run's metrics. */
export type RunMetrics = RunStatistics["metrics"]
/** A group of trades: how many, how many won, and their profit and loss. */
export type Outcome = RunMetrics["breakdowns"]["hour"][string]
/** The robustness summary of a run. */
export type Robustness = RunMetrics["robustness"]
/** Which of the skill's trade counts a run reaches. */
export type SampleSize = Robustness["sample_size"]
/** The fidelity check of a run, or why the engine refused it. */
type AnyFidelityCheck = NonNullable<RunMetrics["fidelity_check"]>
/** The error bar of a run's days at lower fidelity. */
export type FidelityCheck = Extract<AnyFidelityCheck, { kind: "checked" }>
/** A fidelity check the engine refused. */
export type RefusedCheck = Extract<AnyFidelityCheck, { kind: "refused" }>
/** A rerun of the fidelity check against its baseline. */
export type FidelityRerun = FidelityCheck["at_one_minute"]
/** A saved run's account for a chart, in columns. */
export type EquityCurve = Awaited<ReturnType<typeof readEquity>>
/** A saved run's trades as histograms. */
export type TradeDistributions = Awaited<ReturnType<typeof readDistributions>>
/** Trades counted in bins of one width, in columns. */
export type Histogram = TradeDistributions["pnl"]

/** A saved run's metrics, its currency, its net P&L as a share of its capital, its fidelity
 * eras, and its warnings. */
export function runStatisticsQuery(runKey: string) {
  return queryOptions({
    queryKey: ["run-results", runKey, "statistics"],
    queryFn: () => readStatistics(runKey),
    ...KEPT,
  })
}

/** A saved run's equity and drawdown, downsampled by the server. */
export function runEquityQuery(runKey: string) {
  return queryOptions({
    queryKey: ["run-results", runKey, "equity"],
    queryFn: () => readEquity(runKey),
    ...KEPT,
  })
}

/** A saved run's trades as histograms. */
export function runDistributionsQuery(runKey: string) {
  return queryOptions({
    queryKey: ["run-results", runKey, "distributions"],
    queryFn: () => readDistributions(runKey),
    ...KEPT,
  })
}
