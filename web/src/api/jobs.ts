import { queryOptions, useMutation, useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { z } from "zod"
import { api, queryClient } from "./client"
import { followEventStream, type StreamedEvent } from "./event-stream"
import { answer } from "./problems"
import type { components } from "./schema"

/** A job as the server keeps it: its kind, where it stands, how far it has come in percent
 * with its last message, and how it ended. */
export type Job = components["schemas"]["Job"]

/** How long the settings page's demo job counts, as the builder's check asks. */
const DEMO_SECONDS = 60

/** The stream of every job's events, one per shown tab (`useLiveJobs`): Chromium keeps six
 * connections to one host over HTTP/1.1 for all the tabs of the browser. */
const JOBS_STREAM = "/v1/streams/jobs"

/** What the jobs drawer and the home page call each kind of job. */
export const KIND_LABELS: Readonly<Record<Job["kind"], string>> = {
  backtest: "Backtest",
  feature_preview: "Feature preview",
  feature_validate: "Feature validation",
  analytics: "Analytics",
  study: "Study",
  prop_sim: "Prop simulation",
  source_sync: "Data sync",
  import: "Import",
  trade_import: "Trade log import",
  catalog_sync: "Quality check",
  reproduce: "Reproduction",
  agent_turn: "Agent turn",
  ingest: "Upload",
  demo: "Demo job",
  python_snippet: "Python snippet",
}

/** What the jobs drawer calls each status of a job. */
export const STATUS_LABELS: Readonly<Record<Job["status"], string>> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  timed_out: "Timed out",
}

/** A progress event's data, which the OpenAPI document does not type. */
const progressReport = z.object({
  job_id: z.string(),
  percent: z.number(),
  message: z.string(),
})

/** A status event's data, which the OpenAPI document does not type either. */
const statusChange = z.object({ job_id: z.string(), status: z.string() })

/** The statuses of a job that has not ended. */
const ACTIVE_STATUSES: ReadonlySet<string> = new Set(["queued", "running"])

/** How many waits to reconnect before a row asks whether the server still runs: the pauses
 * double from a second, so about seven seconds. */
const WAITS_BEFORE_ASKING = 4

/** The hundred newest jobs, newest first, then the running jobs older than them; read again
 * when a hidden tab is shown, since it followed no stream meanwhile. */
export const jobsQuery = queryOptions({
  queryKey: ["jobs"],
  queryFn: async () => withReportsKept(answer(await api.GET("/v1/jobs"))),
  refetchOnWindowFocus: true,
})

/** `listed`, a read of the jobs, with the figures the cache holds where they are further along
 * for the same attempt of a running job: the read may have left the server before a report the
 * stream has since applied, and would put the bar back. */
export function withReportsKept(listed: Job[]): Job[] {
  const cached = queryClient.getQueryData(jobsQuery.queryKey)
  if (cached === undefined) {
    return listed
  }
  const seen = new Map(cached.map((job) => [job.id, job]))
  return listed.map((job) => {
    const before = seen.get(job.id)
    return before !== undefined &&
      job.status === "running" &&
      before.attempt === job.attempt &&
      before.progress > job.progress
      ? { ...job, progress: before.progress, message: before.message }
      : job
  })
}

/** Whether `job`, or a run in its job's status, is queued or running, and so has progress to
 * follow. */
export function isActive(job: Readonly<Pick<Job, "status">>): boolean {
  return ACTIVE_STATUSES.has(job.status)
}

/** Whether `job` runs on after it was asked to stop, until its worker stops it. */
export function isCancelling(job: Job): boolean {
  return job.status === "running" && job.cancel_requested_at !== null
}

/** Whether `job` ended without doing its work: a cancelled one was stopped on purpose. */
export function hasFailed(job: Readonly<Pick<Job, "status">>): boolean {
  return job.status === "failed" || job.status === "timed_out"
}

/** Whether Run again applies to `job`: it ended and did not succeed. */
export function runsAgain(job: Readonly<Pick<Job, "status">>): boolean {
  return !isActive(job) && job.status !== "succeeded"
}

/** The newest job among `jobs`, newest first, that runs the inputs of `job`: `job` itself, or
 * a Run again of it. */
export function newestRunOf(job: Job, jobs: readonly Job[]): Job {
  const inputs = JSON.stringify(job.payload)
  const newest = jobs.find(
    (each) => each.kind === job.kind && JSON.stringify(each.payload) === inputs
  )
  return newest === undefined ? job : newest
}

/** Start a demo job that counts for a minute. */
export function useDemoJobStart() {
  return useMutation({
    mutationFn: async () =>
      answer(
        await api.POST("/v1/jobs/demo", { body: { seconds: DEMO_SECONDS } })
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  })
}

/** Cancel a job by its id: a queued job ends at once, and a running one is asked to stop,
 * which its status event confirms. */
export function useJobCancellation() {
  return useMutation({
    mutationFn: async (jobId: string) =>
      answer(
        await api.POST("/v1/jobs/{job_id}/cancel", {
          params: { path: { job_id: jobId } },
        })
      ),
    onSuccess: (cancelled) =>
      queryClient.setQueryData(jobsQuery.queryKey, (jobs) =>
        jobs === undefined
          ? jobs
          : jobs.map((job) => (job.id === cancelled.id ? cancelled : job))
      ),
  })
}

/** Run an ended job again from the inputs its row holds, a backtest through its run; its answer
 * is the job that runs them, the one already under way where there is one. */
export function useJobRunAgain() {
  return useMutation({
    mutationFn: async (jobId: string) =>
      answer(
        await api.POST("/v1/jobs/{job_id}/run-again", {
          params: { path: { job_id: jobId } },
        })
      ),
    onSuccess: readTheJobsAgain,
  })
}

/** The jobs, with their progress followed through one stream of every job's events, open while
 * this tab is shown and a job is queued or running: a progress event moves a bar, and a status
 * event asks for the list again, as does each opening of the stream, whose start the server fixes
 * first, so that what the list holds and what the stream sends leave nothing out. `streamNote`
 * is what a running job's row says while the stream waits to connect again. `onLoginEnded` hears a stream the server refused,
 * as once the session ended. The list is also asked again when the window gets the focus, for a
 * job a notebook or another tab started. The shell's top bar calls it once; the drawer and the
 * home page read the same cache. */
export function useLiveJobs(onLoginEnded: () => void) {
  const jobs = useQuery(jobsQuery)
  const shown = useSyncExternalStore(onVisibilityChange, isShown)
  const [waits, setWaits] = useState(0)
  const follows = shown && jobs.data !== undefined && jobs.data.some(isActive)

  useEffect(() => {
    if (!follows) {
      return
    }
    const stop = new AbortController()
    void followEventStream({
      url: JOBS_STREAM,
      signal: stop.signal,
      onEvent: applyJobEvent,
      onOpen: () => {
        setWaits(0)
        readTheJobsAgain()
      },
      onWaiting: () => setWaits((count) => count + 1),
      onRefused: () => {
        setWaits(0)
        onLoginEnded()
      },
    })
    return () => {
      stop.abort()
      setWaits(0)
    }
  }, [follows, onLoginEnded])

  useEffect(() => {
    window.addEventListener("focus", readTheJobsAgain)
    return () => window.removeEventListener("focus", readTheJobsAgain)
  }, [])

  return { jobs, streamNote: reconnectingWords(waits) }
}

/** What a queued or running job's row says after `waits` waits to reconnect. */
export function reconnectingWords(waits: number): string | null {
  if (waits === 0) {
    return null
  }
  return waits < WAITS_BEFORE_ASKING
    ? "Reconnecting"
    : "Reconnecting: is fefat up still running?"
}

function readTheJobsAgain(): void {
  void queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey })
}

function onVisibilityChange(changed: () => void): () => void {
  document.addEventListener("visibilitychange", changed)
  return () => document.removeEventListener("visibilitychange", changed)
}

function isShown(): boolean {
  return document.visibilityState === "visible"
}

/** A job's event in the cache: a report moves the progress of the job it names, never backwards;
 * a change of status asks for the list. */
export function applyJobEvent(event: StreamedEvent): void {
  if (event.event === "status") {
    const change = statusChange.safeParse(parsedJson(event.data))
    if (change.success && change.data.status === "queued") {
      startedOver(change.data.job_id)
    }
    readTheJobsAgain()
    return
  }
  if (event.event !== "progress") {
    return
  }
  const report = progressReport.safeParse(parsedJson(event.data))
  if (!report.success) {
    console.error(
      `Expected a progress report with its job, a percent, and a message, got ${event.data}.`
    )
    return
  }
  const { job_id: jobId, percent, message } = report.data
  queryClient.setQueryData(jobsQuery.queryKey, (jobs) =>
    jobs === undefined
      ? jobs
      : jobs.map((job) =>
          job.id === jobId && percent >= job.progress
            ? { ...job, progress: percent, message }
            : job
        )
  )
}

/** The job `jobId` from the start, as the server left it on queueing it again, so that a report
 * of its earlier attempt that a reconnect replayed keeps no hold on its bar. */
function startedOver(jobId: string): void {
  queryClient.setQueryData(jobsQuery.queryKey, (jobs) =>
    jobs === undefined
      ? jobs
      : jobs.map((job) =>
          job.id === jobId ? { ...job, progress: 0, message: null } : job
        )
  )
}

function parsedJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

/** The jobs among `jobs` that have ended and whose ids `earlier`, the ended jobs of the read
 * before, does not hold. */
export function endedSince(
  earlier: ReadonlySet<string>,
  jobs: readonly Job[]
): readonly Job[] {
  return jobs.filter((job) => !isActive(job) && !earlier.has(job.id))
}

/** A job's end in words, as `Backtest failed`. */
export function endWords(job: Job): string {
  return `${KIND_LABELS[job.kind]} ${STATUS_LABELS[job.status].toLowerCase()}`
}

/** What the jobs button says of the failures not yet seen: the one, or how many. */
export function failureWords(failures: readonly Job[]): string {
  const [first] = failures
  return failures.length === 1
    ? endWords(first)
    : `${failures.length} jobs failed`
}

/** What this tab has seen end, by comparing each read of the list with the one before, the first
 * read saying nothing: `said`, the latest ends in words for a polite live region, and `failures`,
 * those that failed or timed out while the drawer was closed, which `clearFailures` forgets. They
 * live in the open tab alone. A live region reads a change alone, so the same words again end in
 * a period. */
export function useJobEnds(
  jobs: readonly Job[] | undefined,
  drawerOpen: boolean
) {
  const known = useRef<ReadonlySet<string> | null>(null)
  const [failures, setFailures] = useState<readonly Job[]>([])
  const [said, setSaid] = useState("")

  useEffect(() => {
    if (jobs === undefined) {
      return
    }
    const earlier = known.current
    known.current = new Set(
      jobs.filter((job) => !isActive(job)).map((job) => job.id)
    )
    if (earlier === null) {
      return
    }
    const ended = endedSince(earlier, jobs)
    if (ended.length === 0) {
      return
    }
    const words = ended.map(endWords).join(". ")
    setSaid((before) => (before === words ? `${words}.` : words))
    if (!drawerOpen) {
      setFailures((before) => [...before, ...ended.filter(hasFailed)])
    }
  }, [jobs, drawerOpen])

  return { failures, said, clearFailures: () => setFailures([]) }
}
