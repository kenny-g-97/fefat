import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import {
  type ImportAsked,
  type ImportResult,
  useImportStart,
} from "@/api/imports"
import { isActive, type Job, jobsQuery, newestRunOf } from "@/api/jobs"
import type { PreviewState } from "./import-preview"
import type { Asks, ReviewAsked } from "./import-request"

/** An import the wizard started: its draft's asks, as JSON, its job's id, and the request it
 * sent. */
export type Started = Readonly<{
  ask: string
  id: string
  request: ImportAsked
}>

/** Import's state in the review's card, for the draft whose asks are `ask`, as JSON, and the
 * request Import would send now, `request`, of one file or batch or of a round: whether it may
 * send it, the import the wizard started, with its job as the jobs drawer reads it while it
 * runs or the draft is still the one it imports, and the request it sent; whether it imported
 * what the review shows, and the server's refusal of that request. */
export function useImportRun(ask: string | null, request: ImportAsked | null) {
  const start = useImportStart()
  const [started, setStarted] = useState<Started | null>(null)
  const [sentFor, setSentFor] = useState<string | null>(null)
  const jobs = useQuery(jobsQuery)
  const startedJob =
    started === null
      ? undefined
      : jobs.data?.find((each) => each.id === started.id)
  const job =
    startedJob === undefined || jobs.data === undefined
      ? startedJob
      : newestRunOf(startedJob, jobs.data)
  const begun = startedAlready(started, ask, job)
  const shown = started?.ask === ask || (job !== undefined && isActive(job))
  return {
    job: shown ? job : undefined,
    sent: shown ? started?.request : undefined,
    imported: begun && job !== undefined && job.status === "succeeded",
    importable: request !== null && !begun && !start.isPending,
    refusal: start.error !== null && sentFor === ask ? start.error : null,
    importNow: () => {
      if (request !== null && ask !== null) {
        setSentFor(ask)
        start.mutate(request, {
          onSuccess: (queued) => setStarted({ ask, id: queued.id, request }),
        })
      }
    },
  }
}

export type ImportRun = ReturnType<typeof useImportRun>

/** The draft's asks as JSON, which tell its import apart: its files' reviews with the files
 * skipped, which a round leaves out (D-105), where several are chosen, else its review. */
export function importKey(
  asks: Asks,
  skipped: readonly string[]
): string | null {
  if (asks.several.length > 0) {
    return JSON.stringify({ several: asks.several, skipped })
  }
  return asks.review === null ? null : JSON.stringify(asks.review)
}

/** The request Import sends now (web/DESIGN.md, Patterns, Job in its card): the latest draft's,
 * once that draft's own answer says it imports as it is, and none while an older answer is in
 * view, which would be another draft's. */
export function importRequest(
  asks: Asks,
  review: Pick<PreviewState, "answer" | "current">
): ReviewAsked | null {
  const answer = review.answer
  if (!review.current || answer === null) {
    return null
  }
  if (answer.kind !== "file" && answer.kind !== "databento") {
    return null
  }
  return answer.verdict === "imports" ? asks.review : null
}

/** Whether the import of `ask` was started and has not ended without its writes, queued,
 * running, or done, which keeps Import off until the draft changes; one that failed, was
 * cancelled, or ran out of time may be started again, which finishes an import that stopped
 * while it wrote (ADR-0021). */
export function startedAlready(
  started: Pick<Started, "ask"> | null,
  ask: string | null,
  job: Job | undefined
): boolean {
  if (started === null || started.ask !== ask) {
    return false
  }
  return job === undefined || isActive(job) || job.status === "succeeded"
}

type Wrote = Extract<ImportResult, { kind: "wrote" }>

/** What an import kept for the next file, in one sentence: the new profile and the new
 * instrument, which let the next file of the layout import by the profile's name; or why the
 * profile was not kept, though the records were imported. */
export function keptLine(
  result: Wrote
): Readonly<{ text: string; refused: boolean }> | null {
  if (result.profile_refusal !== null) {
    return {
      text: `The records are imported, but the new profile was not kept: ${result.profile_refusal}`,
      refused: true,
    }
  }
  if (result.profile_kept) {
    const saved = result.instrument_saved ? " and the new instrument saved" : ""
    return {
      text: `The new profile is kept${saved}: the next file of this layout imports by the profile's name.`,
      refused: false,
    }
  }
  if (result.instrument_saved) {
    return {
      text: "The new instrument is saved for later imports and loads.",
      refused: false,
    }
  }
  return null
}
