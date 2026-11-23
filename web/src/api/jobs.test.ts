import { afterEach, describe, expect, it, vi } from "vitest"
import { queryClient } from "./client"
import {
  applyJobEvent,
  endedSince,
  endWords,
  failureWords,
  type Job,
  jobsQuery,
  newestRunOf,
  reconnectingWords,
  withReportsKept,
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

  it("keeps a report the list was read too early to hold", () => {
    // That read may have left the server before the report, and would put the bar back.
    queryClient.setQueryData(jobsQuery.queryKey, [aJob("job-1", "running", 60)])

    const [read] = withReportsKept([aJob("job-1", "running", 40)])

    expect([read.progress, read.message]).toEqual([60, "Counted 60 percent"])
  })

  it("takes the list's figure for a new attempt or a job queued again", () => {
    // Done means 1: no figure of an earlier attempt.
    queryClient.setQueryData(jobsQuery.queryKey, [aJob("job-1", "running", 80)])
    const nextAttempt = { ...aJob("job-1", "running", 10), attempt: 2 }

    const [restarted] = withReportsKept([nextAttempt])
    const [queuedAgain] = withReportsKept([aJob("job-1", "queued", 0)])

    expect(restarted.progress).toBe(10)
    expect(queuedAgain.progress).toBe(0)
  })

  it("says Reconnecting, then asks whether the server still runs", () => {
    expect([0, 1, 2, 3, 9].map(reconnectingWords)).toEqual([
      null,
      "Reconnecting",
      "Reconnecting",
      "Reconnecting: is fefat up still running?",
      "Reconnecting: is fefat up still running?",
    ])
  })
})

describe("newestRunOf", () => {
  it("finds the newest job of the same kind and inputs, its Run again", () => {
    const failed = aJob("first", "failed")
    const again = aJob("again", "running")
    const other = { ...aJob("other", "running"), payload: { seconds: 5 } }

    expect(newestRunOf(failed, [other, again, failed])).toBe(again)
    expect(newestRunOf(failed, [other])).toBe(failed)
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
