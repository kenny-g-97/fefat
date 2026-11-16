import { describe, expect, it } from "vitest"
import type { BatchSeen, ImportAsked, ImportResult } from "@/api/imports"
import type { Job } from "@/api/jobs"
import type { Asks } from "./import-request"
import { importRequest, keptLine, startedAlready } from "./import-run"

const ASKED: ImportAsked = {
  kind: "databento",
  source: { kind: "path", path: "D:/batches/GLBX-1" },
  differing: "refuse",
}
const ASKS: Asks = { table: null, review: ASKED, missing: [] }
const ASK = JSON.stringify(ASKED)

function seen(verdict: BatchSeen["verdict"]): BatchSeen {
  return { kind: "databento", verdict, lines: [], merges: [] }
}

function job(status: Job["status"]): Job {
  return {
    id: "0193a000-0000-7000-8000-000000000002",
    kind: "import",
    status,
    attempt: 1,
    max_attempts: 1,
    progress: 0,
    message: null,
    error: null,
    payload: {},
    result: null,
    created_at: "2026-11-15T10:00:00Z",
    started_at: null,
    finished_at: null,
    cancel_requested_at: null,
    lease_expires_at: null,
    worker_pid: null,
  }
}

describe("importRequest", () => {
  it("sends the latest draft's request once its own answer imports as it is", () => {
    expect(
      importRequest(ASKS, { answer: seen("imports"), current: true })
    ).toBe(ASKED)
  })

  it("sends nothing while an older answer is in view, or the answer refuses", () => {
    expect(
      importRequest(ASKS, { answer: seen("imports"), current: false })
    ).toBeNull()
    expect(
      importRequest(ASKS, { answer: seen("refused"), current: true })
    ).toBeNull()
    expect(
      importRequest(ASKS, { answer: seen("differing"), current: true })
    ).toBeNull()
  })
})

describe("startedAlready", () => {
  const started = { ask: ASK, id: job("queued").id }

  it("keeps Import off while the draft's import runs or once it wrote", () => {
    expect(startedAlready(started, ASK, undefined)).toBe(true)
    expect(startedAlready(started, ASK, job("running"))).toBe(true)
    expect(startedAlready(started, ASK, job("succeeded"))).toBe(true)
  })

  it("lets Import start again after a failed, cancelled, or timed-out import", () => {
    expect(startedAlready(started, ASK, job("failed"))).toBe(false)
    expect(startedAlready(started, ASK, job("cancelled"))).toBe(false)
    expect(startedAlready(started, ASK, job("timed_out"))).toBe(false)
  })

  it("lets another draft's import start", () => {
    expect(startedAlready(started, "another", job("running"))).toBe(false)
    expect(startedAlready(null, ASK, undefined)).toBe(false)
  })
})

describe("keptLine", () => {
  const wrote: Extract<ImportResult, { kind: "wrote" }> = {
    kind: "wrote",
    datasets: [],
    instrument_saved: true,
    profile_kept: true,
    profile_refusal: null,
  }

  it("says what the next file of the layout relies on", () => {
    expect(keptLine(wrote)?.text).toBe(
      "The new profile is kept and the new instrument saved: the next file of this layout imports by the profile's name."
    )
    expect(
      keptLine({ ...wrote, instrument_saved: false, profile_kept: false })
    ).toBeNull()
  })

  it("says why a profile was not kept, though the records were imported", () => {
    expect(
      keptLine({
        ...wrote,
        profile_kept: false,
        profile_refusal: "Expected a name no other profile has.",
      })
    ).toEqual({
      text: "The records are imported, but the new profile was not kept: Expected a name no other profile has.",
      refused: true,
    })
  })
})
