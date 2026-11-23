import { afterEach, describe, expect, it, vi } from "vitest"
import { queryClient } from "./client"
import {
  applyJobEvent,
  endedSince,
  endWords,
  failureWords,
  type Job,
  jobsQuery,
} from "./jobs"

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

function report(percent: number, id: string, jobId = "job-1"): void {
  applyJobEvent({
    id,
    event: "progress",
    data: JSON.stringify({
      job_id: jobId,
      percent,
      message: `Counted ${percent} percent`,
    }),
  })
}

afterEach(() => {
  queryClient.clear()
})

describe("applyJobEvent", () => {
  it("moves a job's progress forward with its message, never backwards", () => {
    // A report older than what the list said changes nothing.
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

    applyJobEvent({ id: "5", event: "progress", data: "{not json" })
    applyJobEvent({ id: "6", event: "progress", data: "{}" })

    expect(cachedProgress()).toEqual([[30, "Counted 30 percent"]])
    expect(said.mock.calls).toEqual([
      [
        "Expected a progress report with its job, a percent, and a message, got {not json.",
      ],
      [
        "Expected a progress report with its job, a percent, and a message, got {}.",
      ],
    ])
    said.mockRestore()
  })

  it("asks for the list again when a job's status changes", () => {
    queryClient.setQueryData(jobsQuery.queryKey, [aJob("job-1", "running", 30)])

    applyJobEvent({
      id: "7",
      event: "status",
      data: '{"status": "cancelled", "job_id": "job-1"}',
    })

    expect(queryClient.getQueryState(jobsQuery.queryKey)?.isInvalidated).toBe(
      true
    )
  })
})

describe("one stream", () => {
  it("moves five jobs, each by the job its event names", () => {
    // Done means 1: a fifth active job moves too.
    const ids = ["job-1", "job-2", "job-3", "job-4", "job-5"]
    queryClient.setQueryData(
      jobsQuery.queryKey,
      ids.map((id) => aJob(id, "running"))
    )

    ids.forEach((id, index) => {
      report((index + 1) * 10, String(index), id)
    })

    expect(cachedProgress().map(([percent]) => percent)).toEqual([
      10, 20, 30, 40, 50,
    ])
  })

  it("reads the list once more after a read a report landed during", async () => {
    // That read may have left the server before the report, and would put the bar back; it
    // runs to its end, since reports that keep landing would otherwise stop every read.
    const isInvalidated = () =>
      queryClient.getQueryState(jobsQuery.queryKey)?.isInvalidated
    queryClient.setQueryData(jobsQuery.queryKey, [aJob("job-1", "running", 30)])
    report(40, "1")
    const withNoRead = isInvalidated()
    let answerTheRead: (jobs: Job[]) => void = () => undefined
    const reading = queryClient.fetchQuery({
      queryKey: jobsQuery.queryKey,
      queryFn: () =>
        new Promise<Job[]>((resolve) => {
          answerTheRead = resolve
        }),
      staleTime: 0,
    })

    report(50, "2")
    report(60, "3")
    const duringTheRead = isInvalidated()
    answerTheRead([aJob("job-1", "running", 40)])
    await reading

    expect(withNoRead).toBe(false)
    expect(duringTheRead).toBe(false)
    await vi.waitFor(() => expect(isInvalidated()).toBe(true))
  })
})

describe("the ends of jobs", () => {
  const ended = (id: string, status: Job["status"]) => aJob(id, status)

  it("finds the jobs that ended since the last read, whichever way", () => {
    const jobs = [
      ended("before", "failed"),
      ended("now-failed", "failed"),
      ended("now-cancelled", "cancelled"),
      aJob("still", "running"),
    ]

    expect(endedSince(new Set(["before"]), jobs).map((job) => job.id)).toEqual([
      "now-failed",
      "now-cancelled",
    ])
  })

  it("says each end in the job's kind and status", () => {
    expect(endWords(ended("a", "failed"))).toBe("Demo job failed")
    expect(endWords(ended("b", "timed_out"))).toBe("Demo job timed out")
    expect(endWords(ended("c", "succeeded"))).toBe("Demo job succeeded")
    expect(endWords(ended("d", "cancelled"))).toBe("Demo job cancelled")
  })

  it("names one failure and counts several", () => {
    expect(failureWords([ended("a", "timed_out")])).toBe("Demo job timed out")
    expect(failureWords([ended("a", "failed"), ended("b", "timed_out")])).toBe(
      "2 jobs failed"
    )
  })
})
