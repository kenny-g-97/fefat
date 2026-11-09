import { queryOptions, useMutation, useQuery } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
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

/** How many jobs' streams the shell follows at once: Chromium keeps six connections to one
 * host over HTTP/1.1, so four leave two for the app's own requests. */
const STREAMS_AT_MOST = 4

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
  catalog_sync: "Catalog sync",
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
const progressReport = z.object({ percent: z.number(), message: z.string() })

/** The hundred newest jobs, newest first. */
export const jobsQuery = queryOptions({
  queryKey: ["jobs"],
  queryFn: async () => answer(await api.GET("/v1/jobs")),
})

/** Whether `job` is queued or running, and so has progress to follow. */
export function isActive(job: Job): boolean {
  return job.status === "queued" || job.status === "running"
}

/** Whether `job` runs on after it was asked to stop, until its worker stops it. */
export function isCancelling(job: Job): boolean {
  return job.status === "running" && job.cancel_requested_at !== null
}

/** The ids of the jobs whose streams the shell follows: the running ones first, then the
 * queued, four at most; the others' figures come with the list, which each status event of a
 * followed job asks for again, so that a queued job is followed once it runs. */
export function followedJobIds(jobs: readonly Job[]): readonly string[] {
  const running = jobs.filter((job) => job.status === "running")
  const queued = jobs.filter((job) => job.status === "queued")
  return [...running, ...queued].slice(0, STREAMS_AT_MOST).map((job) => job.id)
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

/** The jobs, with the progress of the queued and running jobs followed through their streams
 * (`followedJobIds`): a progress event moves a bar, and a status event asks for the list again.
 * The shell's top bar calls it once; the drawer and the home page read the same cache. A stream
 * is open only while its job is active, and every stream closes when the shell does, as on
 * logging out. */
export function useLiveJobs() {
  const jobs = useQuery(jobsQuery)
  const followed = useRef(new Map<string, AbortController>())
  const followedIds =
    jobs.data === undefined ? "" : followedJobIds(jobs.data).join(" ")

  useEffect(() => {
    const active = new Set(followedIds === "" ? [] : followedIds.split(" "))
    const streams = followed.current
    for (const [jobId, stop] of streams) {
      if (!active.has(jobId)) {
        stop.abort()
        streams.delete(jobId)
      }
    }
    for (const jobId of active) {
      if (!streams.has(jobId)) {
        streams.set(jobId, followedJob(jobId))
      }
    }
  }, [followedIds])

  useEffect(() => {
    const streams = followed.current
    return () => {
      for (const stop of streams.values()) {
        stop.abort()
      }
      streams.clear()
    }
  }, [])

  return jobs
}

function followedJob(jobId: string): AbortController {
  const stop = new AbortController()
  void followEventStream({
    url: `/v1/streams/job:${jobId}`,
    signal: stop.signal,
    onEvent: (event) => applyJobEvent(jobId, event),
  })
  return stop
}

/** A job's event in the cache: a report moves its progress, never backwards, since a stream
 * opened anew sends its job's events from the first; a change of status asks for the list. */
export function applyJobEvent(jobId: string, event: StreamedEvent): void {
  if (event.event === "status") {
    void queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey })
    return
  }
  if (event.event !== "progress") {
    return
  }
  const report = progressReport.safeParse(parsedJson(event.data))
  if (!report.success) {
    console.error(
      `Expected a progress report of the job ${jobId} with a percent and a message, got ${event.data}.`
    )
    return
  }
  queryClient.setQueryData(jobsQuery.queryKey, (jobs) =>
    jobs === undefined
      ? jobs
      : jobs.map((job) =>
          job.id === jobId && report.data.percent >= job.progress
            ? {
                ...job,
                progress: report.data.percent,
                message: report.data.message,
              }
            : job
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
