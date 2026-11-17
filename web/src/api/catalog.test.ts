import { describe, expect, it } from "vitest"
import {
  endedStoreWrites,
  isSyncing,
  syncsUnderWay,
  writeEndedSince,
} from "./catalog"
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

describe("writeEndedSince", () => {
  it("tells of a sync that ended between two reads of the jobs, seen running or not", () => {
    const older = aSync("1", "succeeded", "ES")
    const ended = aSync("2", "succeeded", "MES")
    const before = endedStoreWrites([older])

    expect(writeEndedSince(before, endedStoreWrites([ended, older]))).toBe(true)
    expect(
      writeEndedSince(
        endedStoreWrites([aSync("2", "running", "MES"), older]),
        endedStoreWrites([ended, older])
      )
    ).toBe(true)
    expect(writeEndedSince(before, endedStoreWrites([older]))).toBe(false)
    expect(
      writeEndedSince(
        endedStoreWrites([ended, older]),
        endedStoreWrites([ended])
      )
    ).toBe(false)
    expect(
      writeEndedSince(
        before,
        endedStoreWrites([{ ...ended, kind: "demo" }, older])
      )
    ).toBe(false)
  })

  it("tells of an import that ended, which wrote the store as a sync does (step 5.12)", () => {
    const older = aSync("1", "succeeded", "ES")
    const imported: Job = { ...aSync("2", "failed", null), kind: "import" }

    expect(
      writeEndedSince(
        endedStoreWrites([older]),
        endedStoreWrites([imported, older])
      )
    ).toBe(true)
  })
})

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
