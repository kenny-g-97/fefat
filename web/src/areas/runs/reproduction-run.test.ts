import { describe, expect, it } from "vitest"
import type { Job } from "@/api/jobs"
import { newestReproductionOf } from "@/api/reproductions"
import { reproductionState } from "./reproduction-run"

const RUN_KEY = "e".repeat(64)

function aJob(changes: Partial<Job>): Job {
  return {
    id: "019d0000-0000-7000-8000-000000000001",
    kind: "reproduce",
    payload: { kind: "backtest", reproduces: RUN_KEY },
    status: "queued",
    progress: 0,
    message: null,
    attempt: 1,
    max_attempts: 3,
    worker_pid: null,
    lease_expires_at: null,
    cancel_requested_at: null,
    result: null,
    error: null,
    created_at: "2026-11-28T10:00:00Z",
    started_at: null,
    finished_at: null,
    ...changes,
  }
}

describe("reproductionState", () => {
  it("follows the job from queued to its verdict, matched, differed, or refused", () => {
    // Step 5.10: a reproduction is a `reproduce` job whose result the run page reads as data.
    const running = aJob({ status: "running", progress: 60 })
    const matched = { verdict: "matched", trades_hash: "c".repeat(64) }
    const refused = {
      verdict: "refused",
      reason: "Expected the data as the run read it.",
    }

    expect(reproductionState(null, false, undefined)).toEqual({ kind: "idle" })
    expect(reproductionState(null, true, undefined)).toEqual({
      kind: "starting",
    })
    expect(reproductionState(null, false, running)).toEqual({
      kind: "running",
      job: running,
    })
    expect(
      reproductionState(
        null,
        false,
        aJob({ status: "succeeded", result: matched })
      )
    ).toEqual({ kind: "answered", reproduction: matched })
    expect(
      reproductionState(
        null,
        false,
        aJob({ status: "succeeded", result: refused })
      )
    ).toEqual({ kind: "answered", reproduction: refused })
  })

  it("says why a reproduction was not had, in the server's words or its own", () => {
    const failed = aJob({
      status: "failed",
      error: "ValueError: Expected a run key.",
    })

    expect(
      reproductionState(new Error("FEAT holds no such run."), false, undefined)
    ).toEqual({
      kind: "failed",
      message: "FEAT holds no such run.",
    })
    expect(reproductionState(null, false, failed)).toEqual({
      kind: "failed",
      message: "ValueError: Expected a run key.",
    })
    expect(
      reproductionState(null, false, aJob({ status: "cancelled" }))
    ).toEqual({
      kind: "failed",
      message: "The reproduction was cancelled. Reproduce the run again.",
    })
    const unread = reproductionState(
      null,
      false,
      aJob({ status: "succeeded", result: { verdict: "maybe" } })
    )
    expect(unread.kind).toBe("failed")
  })
})

describe("newestReproductionOf", () => {
  it("finds the run's newest reproduction among the jobs, newest first", () => {
    const newest = aJob({ id: "newest" })
    const jobs = [
      aJob({
        id: "explain",
        kind: "explain",
        payload: { run_key: RUN_KEY, trade_id: 1 },
      }),
      aJob({
        id: "other run",
        payload: { kind: "backtest", reproduces: "f".repeat(64) },
      }),
      newest,
      aJob({ id: "older" }),
    ]

    expect(newestReproductionOf(RUN_KEY, jobs)).toBe(newest)
    expect(newestReproductionOf("0".repeat(64), jobs)).toBeUndefined()
  })
})
