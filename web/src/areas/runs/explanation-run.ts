import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import {
  type TradeExplanation,
  tradeExplanation,
  useExplainStart,
} from "@/api/explanations"
import {
  isActive,
  type Job,
  jobsQuery,
  newestRunOf,
  runsAgain,
} from "@/api/jobs"
import type { Trade } from "@/api/trades"

/** Where a trade's explanation stands: being queued, its job under way with its progress, its
 * answer, or why it could not be had, in words. */
export type ExplanationState =
  | Readonly<{ kind: "starting" }>
  | Readonly<{ kind: "running"; job: Job }>
  | Readonly<{ kind: "answered"; explanation: TradeExplanation }>
  | Readonly<{ kind: "failed"; message: string }>

/** The explanation the trade review shows (step 5.9), of the trade it was asked for, which keeps
 * the panel while another trade is selected: `explain` queues the `explain` job of a trade and
 * shows it, `close` hides it, and its state follows the job as the jobs drawer reads it, its Run
 * again among it, until its result, the replay's events or its refusal, arrives. */
export function useExplanation(runKey: string) {
  const start = useExplainStart(runKey)
  const jobs = useQuery(jobsQuery)
  const [asked, setAsked] = useState<Readonly<{
    trade: Trade
    jobId: string | null
  }> | null>(null)
  const found =
    asked === null || asked.jobId === null || jobs.data === undefined
      ? undefined
      : jobs.data.find((each) => each.id === asked.jobId)
  const job =
    found !== undefined && jobs.data !== undefined && runsAgain(found)
      ? newestRunOf(found, jobs.data)
      : found
  return {
    trade: asked === null ? null : asked.trade,
    state: explanationState(start.error, start.isPending, job),
    explain: (trade: Trade) => {
      setAsked({ trade, jobId: null })
      start.mutate(trade.entry_order, {
        onSuccess: (queued) => setAsked({ trade, jobId: queued.id }),
      })
    },
    close: () => setAsked(null),
  }
}

/** An explanation's state from its start, `refused` where the server refused to queue it, and
 * its job, none while it is not yet listed. */
export function explanationState(
  refused: Error | null,
  pending: boolean,
  job: Job | undefined
): ExplanationState {
  if (refused !== null) {
    return { kind: "failed", message: refused.message }
  }
  if (pending || job === undefined) {
    return { kind: "starting" }
  }
  if (isActive(job)) {
    return { kind: "running", job }
  }
  if (job.status !== "succeeded") {
    return { kind: "failed", message: failedWords(job) }
  }
  const read = tradeExplanation.safeParse(job.result)
  return read.success
    ? { kind: "answered", explanation: read.data }
    : {
        kind: "failed",
        message: `The explanation's answer could not be read: ${read.error.message} Explain the trade again.`,
      }
}

function failedWords(job: Job): string {
  if (job.status === "cancelled") {
    return "The explanation was cancelled. Explain the trade again."
  }
  return job.error === null
    ? `The explanation ${job.status === "timed_out" ? "ran out of time" : "failed"}. Explain the trade again.`
    : job.error
}
