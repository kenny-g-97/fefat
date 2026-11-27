import { useQuery } from "@tanstack/react-query"
import {
  isActive,
  type Job,
  jobsQuery,
  newestRunOf,
  runsAgain,
} from "@/api/jobs"
import {
  newestReproductionOf,
  type Reproduction,
  reproduction,
  useReproduceStart,
} from "@/api/reproductions"

/** Where a saved run's reproduction stands: none asked for among the recent jobs, being queued,
 * its job under way with its progress, its verdict, or why it could not be had, in words. */
export type ReproductionState =
  | Readonly<{ kind: "idle" }>
  | Readonly<{ kind: "starting" }>
  | Readonly<{ kind: "running"; job: Job }>
  | Readonly<{ kind: "answered"; reproduction: Reproduction }>
  | Readonly<{ kind: "failed"; message: string }>

/** The reproduction a saved run's page shows (step 5.10), its state following the job as the jobs
 * drawer reads it: the one Reproduce queued, or else the run's newest among the recent jobs, so
 * that a reload keeps its verdict, its Run again among it; nothing for a run not saved yet,
 * `null`. */
export function useReproduction(runKey: string | null) {
  const start = useReproduceStart(runKey)
  const jobs = useQuery(jobsQuery)
  const listed = jobs.data
  const pressed = start.data
  const found =
    listed === undefined || runKey === null
      ? pressed
      : pressed === undefined
        ? newestReproductionOf(runKey, listed)
        : listedAs(pressed, listed)
  const job =
    found !== undefined && listed !== undefined && runsAgain(found)
      ? newestRunOf(found, listed)
      : found
  return {
    state: reproductionState(start.error, start.isPending, job),
    reproduce: () => start.mutate(),
  }
}

/** `job` as the list holds it now, further along than the answer that queued it. */
function listedAs(job: Job, listed: readonly Job[]): Job {
  const now = listed.find((each) => each.id === job.id)
  return now === undefined ? job : now
}

/** A reproduction's state from its start, `refused` where the server refused to queue it, and its
 * job, none where none was asked for. */
export function reproductionState(
  refused: Error | null,
  pending: boolean,
  job: Job | undefined
): ReproductionState {
  if (refused !== null) {
    return { kind: "failed", message: refused.message }
  }
  if (pending) {
    return { kind: "starting" }
  }
  if (job === undefined) {
    return { kind: "idle" }
  }
  if (isActive(job)) {
    return { kind: "running", job }
  }
  if (job.status !== "succeeded") {
    return { kind: "failed", message: failedWords(job) }
  }
  const read = reproduction.safeParse(job.result)
  return read.success
    ? { kind: "answered", reproduction: read.data }
    : {
        kind: "failed",
        message: `The reproduction's answer could not be read: ${read.error.message} Reproduce the run again.`,
      }
}

function failedWords(job: Job): string {
  if (job.status === "cancelled") {
    return "The reproduction was cancelled. Reproduce the run again."
  }
  return job.error === null
    ? `The reproduction ${job.status === "timed_out" ? "ran out of time" : "failed"}. Reproduce the run again.`
    : job.error
}
