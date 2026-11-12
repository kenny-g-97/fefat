import { describe, expect, it } from "vitest"
import { isSyncing, syncsUnderWay } from "./catalog"
import type { Job } from "./jobs"

function aSync(id: string, status: Job["status"], root: string | null): Job {
  return {
    id,
    kind: "catalog_sync",
    payload: { root },
    status,
    progress: 0,
    message: null,
    attempt: 1,
    max_attempts: 3,
    worker_pid: null,
    lease_expires_at: null,
    cancel_requested_at: null,
    result: null,
    error: null,
    created_at: "2026-11-12T10:00:00Z",
    started_at: null,
    finished_at: null,
  }
}

describe("syncsUnderWay", () => {
  it("covers the roots of the queued and running syncs alone", () => {
    const cover = syncsUnderWay([
      aSync("1", "running", "MES"),
      aSync("2", "queued", "ES"),
      aSync("3", "succeeded", "MNQ"),
      { ...aSync("4", "running", null), kind: "demo" },
    ])

    expect(cover.every).toBe(false)
    expect(["MES", "ES", "MNQ"].map((root) => isSyncing(cover, root))).toEqual([
      true,
      true,
      false,
    ])
  })

  it("covers every root while a sync of every product runs", () => {
    const cover = syncsUnderWay([aSync("1", "running", null)])

    expect(isSyncing(cover, "MGC")).toBe(true)
  })

  it("refuses a payload the server never writes", () => {
    expect(() =>
      syncsUnderWay([
        { ...aSync("1", "queued", "MES"), payload: { roots: ["MES"] } },
      ])
    ).toThrow()
  })
})
