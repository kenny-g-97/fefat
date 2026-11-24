import { describe, expect, it } from "vitest"
import type { Job } from "./jobs"
import {
  endedBacktests,
  listedBacktests,
  liveRun,
  resultRunKey,
  runAddress,
  type SavedRun,
  type SubmittedRun,
} from "./runs"

const RUN_KEY = "a".repeat(64)

const SETTINGS: SubmittedRun["settings"] = {
  fidelity: "1m",
  latency_ms: 100,
  slippage_ticks: { market: 1, stop: 1 },
  limit_fill: "through",
  roll_handling: "transfer",
  fee_table: "retail-default",
  capital: "50000",
  replay: "skipping",
  provider: "synthetic",
  contract: null,
}

const HEAD = {
  id: "run-1",
  created_at: "2026-11-21T10:00:00Z",
  origin: "manual",
  parameters: { lookback: 12 },
  start: "2026-03-06",
  end: "2026-03-09",
  settings: SETTINGS,
  currency: "USD",
  fee: { kind: "futures", per_contract_side: "2.87" },
} as const

const STRATEGY: NonNullable<SubmittedRun["strategy"]> = {
  strategy_id: "strategy-1",
  name: "demo",
  version_id: "version-1",
  version: 2,
  instrument: "ES",
  timeframe: "5m",
}

const SUBMITTED: SubmittedRun = {
  ...HEAD,
  state: "submitted",
  strategy: STRATEGY,
  status: "queued",
  progress: 30,
  message: null,
  error: null,
  job_id: "job-1",
  cancel_requested_at: null,
}

const SAVED: SavedRun = {
  ...HEAD,
  state: "saved",
  strategy: STRATEGY,
  status: "succeeded",
  progress: 100,
  job_id: null,
  run_key: RUN_KEY,
  key_metrics: {
    pnl: "-2721.560000",
    trades: 18,
    max_drawdown: "2721.560000",
    verdict: "abandon",
  },
}

function aJob(id: string, changes: Partial<Job> = {}): Job {
  return {
    id,
    kind: "backtest",
    payload: {},
    status: "running",
    progress: 0,
    message: null,
    attempt: 1,
    max_attempts: 3,
    worker_pid: null,
    lease_expires_at: null,
    cancel_requested_at: null,
    result: null,
    error: null,
    created_at: "2026-11-21T10:00:00Z",
    started_at: null,
    finished_at: null,
    ...changes,
  }
}

describe("liveRun", () => {
  it("takes its job's fresher figures from the jobs' cache", () => {
    const job = aJob("job-1", {
      progress: 60,
      message: "Running the engine",
      cancel_requested_at: "2026-11-21T10:01:00Z",
    })

    expect(liveRun(SUBMITTED, [job])).toEqual({
      ...SUBMITTED,
      status: "running",
      progress: 60,
      message: "Running the engine",
      cancel_requested_at: "2026-11-21T10:01:00Z",
    })
  })

  it("never moves its bar backwards", () => {
    const earlier = aJob("job-1", { progress: 10 })

    expect(liveRun(SUBMITTED, [earlier]).progress).toBe(30)
  })

  it("leaves a saved run, and one whose job the list no longer holds, as it is", () => {
    const job = aJob("job-1", { progress: 60 })

    expect(liveRun(SAVED, [job])).toBe(SAVED)
    expect(liveRun(SUBMITTED, [aJob("another")])).toBe(SUBMITTED)
    expect(liveRun(SUBMITTED, undefined)).toBe(SUBMITTED)
  })
})

describe("runAddress", () => {
  it("names a saved run by its key and a submission by its row and its job", () => {
    expect(runAddress(SAVED)).toEqual({ key: RUN_KEY })
    expect(runAddress(SUBMITTED)).toEqual({ id: "run-1", job: "job-1" })
  })
})

describe("resultRunKey", () => {
  it("reads the run a backtest's result names, the row it gave way to", () => {
    const ended = aJob("job-1", {
      status: "succeeded",
      result: { run_id: "another-row", run_key: RUN_KEY },
    })

    expect(resultRunKey(ended)).toBe(RUN_KEY)
  })

  it("finds none in a job that failed", () => {
    expect(resultRunKey(aJob("job-1", { status: "failed" }))).toBeNull()
  })
})

describe("listedBacktests", () => {
  it("lists every backtest, whichever way it stands, and no other job", () => {
    // A run that Run again, another tab, or a script started shows in the Runs list at once.
    const jobs = [
      aJob("running"),
      aJob("done", { status: "succeeded" }),
      aJob("import", { kind: "import", status: "running" }),
    ]

    expect(listedBacktests(jobs)).toBe("running done")
  })
})

describe("endedBacktests", () => {
  it("lists the backtests that ended and no other job", () => {
    const jobs = [
      aJob("running"),
      aJob("done", { status: "succeeded" }),
      aJob("failed", { status: "failed" }),
      aJob("import", { kind: "import", status: "succeeded" }),
    ]

    expect(endedBacktests(jobs)).toBe("done failed")
  })
})
