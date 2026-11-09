import { afterEach, describe, expect, it, vi } from "vitest"
import { queryClient } from "./client"
import { applyJobEvent, followedJobIds, type Job, jobsQuery } from "./jobs"

function aJob(id: string, status: Job["status"], progress = 0): Job {
  return {
    id,
    kind: "demo",
    payload: { seconds: 60 },
    status,
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
    queryClient.setQueryData(jobsQuery.queryKey, [aJob("job-1", "running", 30)])

    report(10, "3")
    report(20, "4")
    const replayed = cachedProgress()
    report(40, "6")

    expect(replayed).toEqual([[30, "Counted 30 percent"]])
    expect(cachedProgress()).toEqual([[40, "Counted 40 percent"]])
  })

  it("says when it cannot read a report, and leaves the cache as it was", () => {
    // A report the server reshaped would freeze every bar; the console says why, which the
    // specs' check of the console catches.
    const said = vi.spyOn(console, "error").mockImplementation(() => undefined)
    queryClient.setQueryData(jobsQuery.queryKey, [aJob("job-1", "running", 30)])

    applyJobEvent("job-1", { id: "5", event: "progress", data: "{not json" })
    applyJobEvent("job-1", { id: "6", event: "progress", data: "{}" })

    expect(cachedProgress()).toEqual([[30, "Counted 30 percent"]])
    expect(said.mock.calls).toEqual([
      [
        "Expected a progress report of the job job-1 with a percent and a message, got {not json.",
      ],
      [
        "Expected a progress report of the job job-1 with a percent and a message, got {}.",
      ],
    ])
    said.mockRestore()
  })

  it("asks for the list again when a job's status changes", () => {
    queryClient.setQueryData(jobsQuery.queryKey, [aJob("job-1", "running", 30)])

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

describe("followedJobIds", () => {
  it("follows four active jobs at most, the running ones first", () => {
    // Chromium keeps six connections to one host over HTTP/1.1: four streams leave two.
    const jobs = [
      aJob("queued-1", "queued"),
      aJob("running-1", "running"),
      aJob("ended-1", "succeeded"),
      aJob("queued-2", "queued"),
      aJob("running-2", "running"),
      aJob("running-3", "running"),
    ]

    expect(followedJobIds(jobs)).toEqual([
      "running-1",
      "running-2",
      "running-3",
      "queued-1",
    ])
  })
})
