import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import {
  type ImportAsked,
  type ImportResult,
  useImportStart,
} from "@/api/imports"
import { isActive, type Job, jobsQuery } from "@/api/jobs"
import type { LatestPreview, PreviewState } from "./import-preview"
import type { Asks } from "./import-request"

/** An import the wizard started: the review's ask it sent, as JSON, and its job's id. */
export type Started = Readonly<{ ask: string; id: string }>

/** Import's state in the review's card: whether it may send the latest draft's request now,
 * the import the wizard started, with its job as the jobs drawer reads it while it runs or the
 * draft is still the one it imports, whether it imported what the review shows, and the
 * server's refusal of that request. */
export function useImportRun(asks: Asks, review: LatestPreview) {
  const start = useImportStart()
  const [started, setStarted] = useState<Started | null>(null)
  const jobs = useQuery(jobsQuery)
  const job =
    started === null
      ? undefined
      : jobs.data?.find((each) => each.id === started.id)
  const ask = asks.review === null ? null : JSON.stringify(asks.review)
  const request = importRequest(asks, review)
  const begun = startedAlready(started, ask, job)
  const shown = started?.ask === ask || (job !== undefined && isActive(job))
  return {
    job: shown ? job : undefined,
    imported: begun && job !== undefined && job.status === "succeeded",
    importable: request !== null && !begun && !start.isPending,
    refusal:
      start.error !== null && JSON.stringify(start.variables) === ask
        ? start.error
        : null,
    importNow: () => {
      if (request !== null && ask !== null) {
        start.mutate(request, {
          onSuccess: (queued) => setStarted({ ask, id: queued.id }),
        })
      }
    },
  }
}

export type ImportRun = ReturnType<typeof useImportRun>

/** The request Import sends now (web/DESIGN.md, Patterns, Job in its card): the latest draft's,
 * once that draft's own answer says it imports as it is, and none while an older answer is in
 * view, which would be another draft's. */
export function importRequest(
  asks: Asks,
  review: Pick<PreviewState, "answer" | "current">
): ImportAsked | null {
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
  started: Started | null,
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
