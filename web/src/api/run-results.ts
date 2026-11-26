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

async function readMonteCarlo(run: string) {
  return answer(
    await api.GET("/v1/runs/{run}/monte-carlo", { params: { path: { run } } })
  )
}

async function readResultsBySide(run: string) {
  return answer(
    await api.GET("/v1/runs/{run}/results", { params: { path: { run } } })
  )
}

async function readMarketExposure(run: string) {
  return answer(
    await api.GET("/v1/runs/{run}/market", { params: { path: { run } } })
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
/** A saved run's Monte Carlo, or why a run of fewer than two trades has none. */
export type MonteCarloAnswer = Awaited<ReturnType<typeof readMonteCarlo>>
/** Paths of a saved run's trades drawn again with replacement (step 5.20). */
export type MonteCarlo = Extract<MonteCarloAnswer, { kind: "resampled" }>
/** The paths' equity at five percentiles after each count of trades, and the run's own, in
 * columns. */
export type EquityFan = MonteCarlo["fan"]
/** The paths' figures at each whole percent of them, each beside the run's own (step 5.21). */
export type FiguresByPercent = MonteCarlo["by_percent"]
/** A figure of the paths that a chart draws against the percent of them. */
export type PathFigure = keyof FiguresByPercent
/** One figure of the paths at each whole percent of them from 0 to 100, none where a path has
 * none, as one that drew no losing trade has no profit factor, and the run's own. */
export type FigureAtPercents = FiguresByPercent[PathFigure]
/** A saved run's figures for all its trades, its long trades, and its short trades, a side none
 * where the run made no trade on it (step 5.22). */
export type ResultsBySide = Awaited<ReturnType<typeof readResultsBySide>>
/** The figures of a run's trades of one side, or of all of them. */
export type SideResults = ResultsBySide["all_trades"]
/** A saved run's market exposure, how its days moved with one lot of its instrument held long,
 * with buy and hold beside it (step 5.23). */
export type MarketExposure = Awaited<ReturnType<typeof readMarketExposure>>
/** How a run's days moved with the market's over some of them. */
export type DaysExposure = MarketExposure["falling_days"]
/** Why a figure of a market exposure reads None. */
export type Uncounted = NonNullable<DaysExposure["uncounted"]>
/** Buy and hold at one lot and, where the volatility counts, at the run's, told apart by `kind`. */
export type BuyAndHold = MarketExposure["buy_and_hold"]
/** Buy and hold at one lot and at the run's volatility, with that size's curve. */
export type SizedBuyAndHold = Extract<BuyAndHold, { kind: "sized" }>
/** Buy and hold's figures at one size. */
export type BuyAndHoldFigures = BuyAndHold["at_one_lot"]
/** Buy and hold's equity at the run's volatility, at the equity curve's decisions. */
export type BuyAndHoldCurve = SizedBuyAndHold["curve"]

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

/** A saved run's Monte Carlo as the server draws it unless asked otherwise: 1,000 paths from
 * seed 0, the same each read. */
export function runMonteCarloQuery(runKey: string) {
  return queryOptions({
    queryKey: ["run-results", runKey, "monte-carlo"],
    queryFn: () => readMonteCarlo(runKey),
    ...KEPT,
  })
}

/** A saved run's figures for all, long, and short trades. */
export function runResultsBySideQuery(runKey: string) {
  return queryOptions({
    queryKey: ["run-results", runKey, "by-side"],
    queryFn: () => readResultsBySide(runKey),
    ...KEPT,
  })
}

/** A saved run's market exposure and buy and hold, its curve at the decisions the equity's
 * answer keeps, which the market exposure card and the equity chart share. */
export function runMarketQuery(runKey: string) {
  return queryOptions({
    queryKey: ["run-results", runKey, "market"],
    queryFn: () => readMarketExposure(runKey),
    ...KEPT,
  })
}
