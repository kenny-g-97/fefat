import {
  infiniteQueryOptions,
  queryOptions,
  useMutation,
} from "@tanstack/react-query"
import { z } from "zod"
import { useReadOnceEnded } from "./catalog"
import { api, queryClient } from "./client"
import { isActive, type Job, jobsQuery } from "./jobs"
import { answer } from "./problems"
import type { components } from "./schema"
import { strategiesQuery } from "./strategies"

/** A run whose job has yet to save it. */
export type SubmittedRun = components["schemas"]["SubmittedRun"]
/** A run whose folder is saved, with what a list shows of how it went. */
export type SavedRun = components["schemas"]["SavedRun"]
/** A run as a list shows it, told apart by its `state`. */
export type ListedRun = SubmittedRun | SavedRun
/** What a run would read, before anything runs. */
export type RunEstimated = components["schemas"]["RunEstimated"]
/** What `POST /v1/runs` takes. */
export type RunSubmission = components["schemas"]["RunSubmission"]
/** What `POST /v1/runs/estimate` takes. */
export type RunEstimateRequest = components["schemas"]["RunEstimateRequest"]

/** What the Runs page's filters ask of the list. */
export type RunFilters = Readonly<{
  strategy?: string
  versioned?: false
  status?: Job["status"]
}>

/** What the app calls each robustness verdict of a saved run. */
export const VERDICT_LABELS: Readonly<
  Record<SavedRun["key_metrics"]["verdict"], string>
> = {
  deploy_grade_evidence: "Deploy-grade evidence",
  refine: "Refine",
  abandon: "Abandon",
}

/** How many of the newest runs Home's card shows. */
const RECENT_RUNS = 5

/** What a backtest job's result names (`fefat_app.jobs.backtests`), the row that holds its run,
 * which the OpenAPI document does not type. */
const backtestResult = z.object({ run_id: z.string(), run_key: z.string() })

/** The address of a run's page: a saved run's key, which a rebuild of the index keeps, or a
 * submission's row with its job, whose result names the run should the row give way. */
export function runAddress(
  run: ListedRun
): Readonly<{ key: string } | { id: string; job: string }> {
  return run.state === "saved"
    ? { key: run.run_key }
    : { id: run.id, job: run.job_id }
}

/** The run key a backtest job's result names, none for a job without one, as one that failed. */
export function resultRunKey(job: Job): string | null {
  const read = backtestResult.safeParse(job.result)
  return read.success ? read.data.run_key : null
}

/** The runs, newest first, a page at a time, narrowed by `filters`; a list reads the run folders
 * no row holds first, so that a run a notebook saved is listed. */
export function runsQuery(filters: RunFilters) {
  return infiniteQueryOptions({
    queryKey: ["runs", "list", filters],
    queryFn: async ({ pageParam }: { pageParam: string | null }) =>
      answer(
        await api.GET("/v1/runs", {
          params: {
            query: {
              ...filters,
              ...(pageParam === null ? {} : { cursor: pageParam }),
            },
          },
        })
      ),
    initialPageParam: null,
    getNextPageParam: (page) => page.next_cursor,
  })
}

/** The newest runs, for Home's card. */
export const recentRunsQuery = queryOptions({
  queryKey: ["runs", "recent"],
  queryFn: async () =>
    answer(
      await api.GET("/v1/runs", { params: { query: { limit: RECENT_RUNS } } })
    ),
})

/** A run by its id or its run key, with its metrics once saved. */
export function runQuery(run: string) {
  return queryOptions({
    queryKey: ["runs", "one", run],
    queryFn: async () =>
      answer(await api.GET("/v1/runs/{run}", { params: { path: { run } } })),
  })
}

/** The job `jobId`, whose result names the run a submission's row gave way to. */
export function runJobQuery(jobId: string) {
  return queryOptions({
    queryKey: ["runs", "job", jobId],
    queryFn: async () =>
      answer(
        await api.GET("/v1/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
        })
      ),
  })
}

/** What a run of a version would read under `asked`; a read no form waits for any longer is
 * given up, so that it holds none of the browser's few connections beside the jobs' streams. */
export function runEstimateQuery(asked: RunEstimateRequest) {
  return queryOptions({
    queryKey: ["runs", "estimate", asked],
    queryFn: async ({ signal }) =>
      answer(await api.POST("/v1/runs/estimate", { body: asked, signal })),
  })
}

/** Read again what a new or a cancelled run changes: the lists, the run, and the jobs. */
function readRunsAgain(): void {
  void queryClient.invalidateQueries({ queryKey: ["runs"] })
  void queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey })
}

/** Ask for a backtest: its answer is the saved run where its request finds one, else the run
 * whose job is queued. */
export function useRunSubmission() {
  return useMutation({
    mutationFn: async (asked: RunSubmission) =>
      answer(await api.POST("/v1/runs", { body: asked })),
    onSuccess: readRunsAgain,
  })
}

/** Ask for a backtest and the same at one and at two more ticks of slippage. */
export function useStressSubmission() {
  return useMutation({
    mutationFn: async (asked: RunSubmission) =>
      answer(await api.POST("/v1/runs/stress", { body: asked })),
    onSuccess: readRunsAgain,
  })
}

/** Cancel a run's job: at once while it is queued, asked while it runs. */
export function useRunCancellation() {
  return useMutation({
    mutationFn: async (run: string) =>
      answer(
        await api.POST("/v1/runs/{run}/cancel", { params: { path: { run } } })
      ),
    onSuccess: readRunsAgain,
  })
}

/** `run` with its job's fresher figures from the jobs' cache, which the streams keep live: its
 * status, its message and error, when it was asked to stop, and its progress, never backwards. A
 * saved run, or one whose job the list no longer holds, is as it is. */
export function liveRun<Run extends ListedRun>(
  run: Run,
  jobs: readonly Job[] | undefined
): Run {
  if (run.state !== "submitted" || jobs === undefined) {
    return run
  }
  const job = jobs.find((each) => each.id === run.job_id)
  if (job === undefined) {
    return run
  }
  return {
    ...run,
    status: job.status,
    progress: Math.max(run.progress, job.progress),
    message: job.message,
    error: job.error,
    cancel_requested_at: job.cancel_requested_at,
  }
}

/** The ids of the backtests among `jobs` that ended, as one text a hook's dependency can compare
 * from one read of the jobs to the next. */
export function endedBacktests(jobs: readonly Job[]): string {
  return jobs
    .filter((job) => job.kind === "backtest" && !isActive(job))
    .map((job) => job.id)
    .join(" ")
}

/** Read again, on every page, the runs and the strategies' last runs once a backtest among
 * `jobs` ends: one a later read of the jobs lists as ended for the first time. The shell's top
 * bar calls it once. */
export function useRunsReadAfterBacktests(
  jobs: readonly Job[] | undefined
): void {
  useReadOnceEnded(
    jobs === undefined ? undefined : endedBacktests(jobs),
    readRunsAndStrategiesAgain
  )
}

function readRunsAndStrategiesAgain(): void {
  void queryClient.invalidateQueries({ queryKey: ["runs"] })
  void queryClient.invalidateQueries({ queryKey: strategiesQuery.queryKey })
}
