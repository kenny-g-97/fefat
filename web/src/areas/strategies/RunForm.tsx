import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { ApiProblem, isRefusal } from "@/api/problems"
import {
  type ListedRun,
  type RunEstimated,
  type RunSubmission,
  readRunEstimate,
  runEstimateQuery,
  useRunSubmission,
  useStressSubmission,
} from "@/api/runs"
import type { SavedStrategyVersion } from "@/api/strategies"
import { Button } from "@/ui/button"
import { SchemaForm } from "@/ui/schema-form"
import { SectionFailure } from "@/ui/section-failure"
import { TextLink } from "@/ui/text-link"
import {
  estimateAsked,
  type RunDraft,
  type RunReadiness,
  readWords,
  runReadiness,
} from "./run-draft"
import { RunCostFields } from "./RunCostFields"
import { RunDataFields } from "./RunDataFields"
import { hasKeptDraft } from "./strategy-drafts"

type RunFormProps = Readonly<{
  version: SavedStrategyVersion
  draft: RunDraft
  lastEstimate: RunEstimated | null
  onEstimated: (estimate: RunEstimated) => void
  onChange: (draft: RunDraft) => void
}>

/** The dialog's form (web/DESIGN.md, Patterns, Run backtest dialog), drawn from the estimate of
 * what the run would read, which is asked again as a choice that changes it is made. Its last
 * answer, which the dialog keeps for a form opened again, stays in view while a newer one is
 * read, and after a refusal, so that the choice the server refused can be changed back. */
export function RunForm({
  version,
  draft,
  lastEstimate,
  onEstimated,
  onChange,
}: RunFormProps) {
  const estimate = useQuery(runEstimateQuery(estimateAsked(version.id, draft)))
  const answer = estimate.data
  const estimated = answer?.state === "estimated" ? answer : null
  useEffect(() => {
    if (estimated !== null) {
      onEstimated(estimated)
    }
  }, [estimated, onEstimated])
  if (answer?.state === "no_data") {
    return (
      <div className="flex flex-col items-start gap-3">
        <p role="alert" className="text-foreground-secondary">
          {`FEAT holds no data of ${answer.instrument}. Import its bars or ticks, then run this strategy.`}
        </p>
        <TextLink to="/data/import">Import data</TextLink>
      </div>
    )
  }
  const known = estimated === null ? lastEstimate : estimated
  if (known === null) {
    return estimate.status === "error" ? (
      <SectionFailure
        error={estimate.error}
        onRetry={() => void estimate.refetch()}
      />
    ) : (
      <p role="status" className="min-h-24 text-foreground-secondary">
        Counting what this run would read
      </p>
    )
  }
  return (
    <FilledForm
      version={version}
      draft={draft}
      estimate={known}
      latest={estimate.status === "success" && !estimate.isFetching}
      failure={estimate.status === "error" ? estimate.error : null}
      onRetry={() => void estimate.refetch()}
      onChange={onChange}
    />
  )
}

type FilledFormProps = Readonly<{
  version: SavedStrategyVersion
  draft: RunDraft
  estimate: RunEstimated
  latest: boolean
  failure: Error | null
  onRetry: () => void
  onChange: (draft: RunDraft) => void
}>

function FilledForm({
  version,
  draft,
  estimate,
  latest,
  failure,
  onRetry,
  onChange,
}: FilledFormProps) {
  const [draftKept] = useState(() =>
    hasKeptDraft(version.name, version.version, version.code)
  )
  const form = useRef<HTMLDivElement>(null)
  useEffect(() => {
    form.current?.querySelector<HTMLElement>("input, button")?.focus()
  }, [])
  return (
    <div ref={form} className="flex flex-col gap-5">
      {draftKept && (
        <p data-testid="run-draft-note" className="text-foreground-secondary">
          {`Your draft is not saved: this runs version ${version.version} as saved.`}
        </p>
      )}
      <RunDataFields draft={draft} estimate={estimate} onChange={onChange} />
      <RunCostFields draft={draft} estimate={estimate} onChange={onChange} />
      <section aria-label="Parameters" className="flex flex-col gap-3">
        <h3 className="text-sm leading-none font-medium text-foreground">
          Parameters
        </h3>
        <SchemaForm
          schema={version.parameter_schema}
          idPrefix={`run-parameter-v${version.version}`}
          entered={draft.entered}
          onChange={(parameters, entered) =>
            onChange({ ...draft, parameters, entered })
          }
        />
      </section>
      {failure !== null &&
        (isRefusal(failure, 400) ? (
          <p
            role="alert"
            data-testid="run-estimate-refusal"
            className="text-negative"
          >
            {failure.message}
          </p>
        ) : (
          <SectionFailure error={failure} onRetry={onRetry} />
        ))}
      <RunActions
        version={version}
        draft={draft}
        estimate={estimate}
        latest={latest}
        failure={failure}
      />
    </div>
  )
}

type RunActionsProps = Readonly<{
  version: SavedStrategyVersion
  draft: RunDraft
  estimate: RunEstimated
  latest: boolean
  failure: Error | null
}>

/** What the run would read, why it waits where it does, and its two actions: Run backtest, and
 * Run with stress, which adds the same run at one and at two more ticks of slippage. A run found
 * saved opens as Cached; a run queued opens on its page, which follows its job. A press while the
 * estimate is read, as leaving a typed date by pressing makes it, is kept until its answer. */
function RunActions({
  version,
  draft,
  estimate,
  latest,
  failure,
}: RunActionsProps) {
  const navigate = useNavigate()
  const submission = useRunSubmission()
  const stress = useStressSubmission()
  const [holding, setHolding] = useState(false)
  const readiness = runReadiness(version.id, draft, estimate, latest)
  const sending = submission.isPending || stress.isPending || holding
  const closed = failure !== null || readiness.kind === "waiting" || sending
  const failed = submission.error ?? stress.error
  const open = (run: ListedRun) =>
    void navigate(
      run.state === "saved"
        ? {
            to: "/runs/run",
            search: { key: run.run_key },
            state: { cachedRun: run.run_key },
          }
        : { to: "/runs/run", search: { id: run.id, job: run.job_id } }
    )
  const launch = (request: RunSubmission) => {
    stress.reset()
    submission.mutate(request, { onSuccess: open })
  }
  const launchWithStress = (request: RunSubmission) => {
    submission.reset()
    stress.mutate(request, {
      onSuccess: () =>
        void navigate({
          to: "/runs",
          search: { strategy: version.name },
          state: { stressed: version.name },
        }),
    })
  }
  const press = async (send: (request: RunSubmission) => void) => {
    if (readiness.kind === "ready") {
      send(readiness.request)
      return
    }
    setHolding(true)
    const fresh = await readRunEstimate(estimateAsked(version.id, draft))
    setHolding(false)
    if (fresh?.state === "estimated") {
      const read = runReadiness(version.id, draft, fresh, true)
      if (read.kind === "ready") {
        send(read.request)
      }
    }
  }
  return (
    <footer className="sticky -bottom-6 -mx-6 -mb-6 flex flex-col gap-3 border-t bg-card px-6 pt-5 pb-6">
      <div className="flex flex-col gap-1">
        <p data-testid="run-estimate" className="font-medium text-foreground">
          {readWords(estimate)}
        </p>
        <p
          data-testid="run-stress-note"
          className="text-xs text-muted-foreground"
        >
          Run with stress also runs it at 1 and at 2 more ticks of slippage
        </p>
      </div>
      {failed !== null && (
        <p
          role="alert"
          data-testid="run-refusal"
          className="text-negative wrap-anywhere"
        >
          {refusalWords(failed)}
        </p>
      )}
      <div className="flex items-center justify-between gap-3">
        <p
          role="status"
          data-testid="run-waiting"
          className="min-w-0 text-xs text-muted-foreground"
        >
          {sending ? "Looking the run up" : waitingWords(failure, readiness)}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="ghost"
            data-testid="run-stress"
            disabled={closed}
            onClick={() => void press(launchWithStress)}
          >
            Run with stress
          </Button>
          <Button
            data-testid="run-launch"
            disabled={closed}
            onClick={() => void press(launch)}
          >
            Run backtest
          </Button>
        </div>
      </div>
    </footer>
  )
}

/** Why the two actions wait, in words, where they do. */
function waitingWords(failure: Error | null, readiness: RunReadiness): string {
  if (failure !== null) {
    return isRefusal(failure, 400)
      ? "Change the choice refused above"
      : "Read the data again above"
  }
  if (readiness.kind === "reading") {
    return "Reading your latest change"
  }
  return readiness.kind === "waiting" ? readiness.why : ""
}

/** A refusal in the server's words, at its line of the code where it names one. */
function refusalWords(error: Error): string {
  return error instanceof ApiProblem && error.line !== null
    ? `Line ${error.line}: ${error.message}`
    : error.message
}
