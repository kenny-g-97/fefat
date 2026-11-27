import { describe, expect, it } from "vitest"
import type { Job } from "@/api/jobs"
import { explanationState } from "./explanation-run"

function aJob(changes: Partial<Job>): Job {
  return {
    id: "019d0000-0000-7000-8000-000000000001",
    kind: "explain",
    payload: { run_key: "e".repeat(64), trade_id: 7 },
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
    created_at: "2026-11-27T10:00:00Z",
    started_at: null,
    finished_at: null,
    ...changes,
  }
}

const EXPLAINED = {
  kind: "explained",
  trade_id: 7,
  heading: "Trade 7: long 1 ESH2026 at 6858",
  started_at: "2026-03-06T02:49:58.151893784Z",
  events: [
    {
      time: "2026-03-06T02:50:11.668134794Z",
      kind: "filled",
      order: 7,
      rule: "F-MKT-01",
      text: "order 7: buy 1 at 6858, taker",
    },
  ],
  fills: [],
}

describe("explanationState", () => {
  it("follows the job from queued to its answer, the replay's events or its refusal", () => {
    // Step 5.9: the explanation is an `explain` job whose result the panel reads as data.
    const running = aJob({ status: "running", progress: 0 })
    const refused = { kind: "refused", trade_id: 7, reason: "Expected trades." }

    expect(explanationState(null, true, undefined)).toEqual({
      kind: "starting",
    })
    expect(explanationState(null, false, running)).toEqual({
      kind: "running",
      job: running,
    })
    expect(
      explanationState(
        null,
        false,
        aJob({ status: "succeeded", result: EXPLAINED })
      )
    ).toEqual({ kind: "answered", explanation: EXPLAINED })
    expect(
      explanationState(
        null,
        false,
        aJob({ status: "succeeded", result: refused })
      )
    ).toEqual({ kind: "answered", explanation: refused })
  })

  it("says why where the start was refused, the job did not end well, or its answer is unread", () => {
    const words = (job: Job) => {
      const state = explanationState(null, false, job)
      return state.kind === "failed" ? state.message : state.kind
    }

    expect(
      explanationState(
        new Error("Expected the id of a trade."),
        false,
        undefined
      )
    ).toEqual({
      kind: "failed",
      message: "Expected the id of a trade.",
    })
    expect(words(aJob({ status: "failed", error: "ValueError: broken" }))).toBe(
      "ValueError: broken"
    )
    expect(words(aJob({ status: "cancelled" }))).toBe(
      "The explanation was cancelled. Explain the trade again."
    )
    expect(words(aJob({ status: "timed_out" }))).toBe(
      "The explanation ran out of time. Explain the trade again."
    )
    expect(
      words(aJob({ status: "succeeded", result: { kind: "other" } }))
    ).toMatch(/^The explanation's answer could not be read: /)
  })
})
