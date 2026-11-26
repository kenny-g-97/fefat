import { z } from "zod"

/** The statuses a run takes, its job's until it is saved. */
export const RUN_STATUSES = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
] as const

/** What the Runs page's filters ask, kept in its address so that a reload, the way back from a
 * run, and a link keep them; a value the page cannot read is left out. A strategy's name, or
 * `versioned` false for the runs that name no saved version. */
export const runsSearch = z.object({
  strategy: z.string().min(1).max(64).optional().catch(undefined),
  versioned: z.literal(false).optional().catch(undefined),
  status: z.enum(RUN_STATUSES).optional().catch(undefined),
})

export type RunsSearch = z.infer<typeof runsSearch>

/** A run's page: a saved run by its key, which a rebuild of the index keeps, or a submission by
 * its row's id with its job, whose result names the run should its row give way to another. */
export const runSearch = z.object({
  key: z
    .string()
    .regex(/^[0-9a-f]{64}$/)
    .optional()
    .catch(undefined),
  id: z.string().min(1).max(64).optional().catch(undefined),
  job: z.string().min(1).max(64).optional().catch(undefined),
})

/** A saved run's results in full (step 5.22): the run by its key alone, since only a saved run
 * has results. */
export const allResultsSearch = runSearch.pick({ key: true })
