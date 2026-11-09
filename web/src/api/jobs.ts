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

/** The jobs, with the progress of each queued or running job followed through its stream: a
 * progress event moves its bar, and a status event asks for the list again. The shell's top
 * bar calls it once; the drawer and the home page read the same cache. A stream is open only
 * while its job is active, and every stream closes when the shell does, as on logging out. */
export function useLiveJobs() {
  const jobs = useQuery(jobsQuery)
  const followed = useRef(new Map<string, AbortController>())
  const activeIds =
    jobs.data === undefined
      ? ""
      : jobs.data
          .filter(isActive)
          .map((job) => job.id)
          .join(" ")

  useEffect(() => {
    const active = new Set(activeIds === "" ? [] : activeIds.split(" "))
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
  }, [activeIds])

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
