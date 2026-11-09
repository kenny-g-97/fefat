import { afterEach, describe, expect, it } from "vitest"
import { queryClient } from "./client"
import { applyJobEvent, type Job, jobsQuery } from "./jobs"

function aRunningJob(progress: number): Job {
  return {
    id: "job-1",
    kind: "demo",
    payload: { seconds: 60 },
    status: "running",
    progress,
    message: `Counted ${progress} percent`,
    attempt: 1,
    max_attempts: 3,
    worker_pid: 4242,
    lease_expires_at: "2026-11-09T10:00:15Z",
    cancel_requested_at: null,
    result: null,
    error: null,
    created_at: "2026-11-09T10:00:00Z",
    started_at: "2026-11-09T10:00:01Z",
    finished_at: null,
  }
}

function cachedProgress(): readonly (readonly [number, string | null])[] {
  const jobs = queryClient.getQueryData(jobsQuery.queryKey)
  if (jobs === undefined) {
    throw new Error("Expected the jobs in the cache, got none.")
  }
  return jobs.map((job) => [job.progress, job.message])
}

function report(percent: number, id: string): void {
  applyJobEvent("job-1", {
    id,
    event: "progress",
    data: JSON.stringify({ percent, message: `Counted ${percent} percent` }),
  })
}

afterEach(() => {
  queryClient.clear()
})

describe("applyJobEvent", () => {
  it("moves a job's progress forward with its message, never backwards", () => {
    // A stream opened anew sends its job's reports from the first: older ones change nothing.
    queryClient.setQueryData(jobsQuery.queryKey, [aRunningJob(30)])

    report(10, "3")
    report(20, "4")
    const replayed = cachedProgress()
    report(40, "6")

    expect(replayed).toEqual([[30, "Counted 30 percent"]])
    expect(cachedProgress()).toEqual([[40, "Counted 40 percent"]])
  })

  it("leaves the cache as it was for a report it cannot read", () => {
    queryClient.setQueryData(jobsQuery.queryKey, [aRunningJob(30)])

    applyJobEvent("job-1", { id: "5", event: "progress", data: "{not json" })
    applyJobEvent("job-1", { id: "6", event: "progress", data: "{}" })

    expect(cachedProgress()).toEqual([[30, "Counted 30 percent"]])
  })

  it("asks for the list again when a job's status changes", () => {
    queryClient.setQueryData(jobsQuery.queryKey, [aRunningJob(30)])

    applyJobEvent("job-1", {
      id: "7",
      event: "status",
      data: '{"status": "cancelled"}',
    })

    expect(queryClient.getQueryState(jobsQuery.queryKey)?.isInvalidated).toBe(
      true
    )
  })
})
