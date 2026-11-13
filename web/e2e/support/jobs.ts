import { type APIRequestContext, expect, type Locator } from "@playwright/test"
import { z } from "zod"

const identity = z.object({ csrf_token: z.string() })
const listedJobs = z.array(z.object({ id: z.string(), status: z.string() }))
const ACTIVE = new Set(["queued", "running"])
const CREATED = "2026-11-09T10:00:00Z"

/** A job as `GET /v1/jobs` lists one, for a spec that answers the list itself: a demo job of a
 * minute, queued a moment ago, with `changes` over it. */
export function aJob(
  id: string,
  status: string,
  changes: Readonly<Record<string, unknown>> = {}
) {
  return {
    id,
    kind: "demo",
    payload: { seconds: 60 },
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
    created_at: CREATED,
    started_at: null,
    finished_at: null,
    ...changes,
  }
}

/** Start `count` demo jobs of a minute through the API with the context's session. */
export async function startDemoJobs(
  request: APIRequestContext,
  count: number
): Promise<void> {
  const { csrf_token } = identity.parse(
    await (await request.get("/v1/me")).json()
  )
  for (let started = 0; started < count; started += 1) {
    const demo = await request.post("/v1/jobs/demo", {
      data: { seconds: 60 },
      headers: { "X-CSRF-Token": csrf_token },
    })
    expect(demo.status()).toBe(202)
  }
}

/** Cancel every queued or running job through the API with the context's session, and wait
 * until none is left, so that a later spec finds no job running: the shell keeps a job's
 * stream open while it runs, which `networkidle` would wait on for ever. */
export async function cancelActiveJobs(
  request: APIRequestContext
): Promise<void> {
  const me = await request.get("/v1/me")
  if (me.status() === 401) {
    return
  }
  const { csrf_token } = identity.parse(await me.json())
  for (const id of await activeJobIds(request)) {
    const cancelled = await request.post(`/v1/jobs/${id}/cancel`, {
      headers: { "X-CSRF-Token": csrf_token },
    })
    expect(cancelled.status()).toBe(200)
  }
  await expect
    .poll(async () => (await activeJobIds(request)).length, {
      timeout: 30_000,
    })
    .toBe(0)
}

/** The value a progress bar shows, from its `aria-valuenow`. */
export async function progressOf(bar: Locator): Promise<number> {
  const value = await bar.getAttribute("aria-valuenow")
  if (value === null) {
    throw new Error("Expected a progress bar with aria-valuenow, got none.")
  }
  return Number(value)
}

async function activeJobIds(request: APIRequestContext): Promise<string[]> {
  const listed = await request.get("/v1/jobs")
  expect(listed.status()).toBe(200)
  return listedJobs
    .parse(await listed.json())
    .filter((job) => ACTIVE.has(job.status))
    .map((job) => job.id)
}
