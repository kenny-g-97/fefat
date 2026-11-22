import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { ApiProblem } from "@/api/problems"
import {
  type ListedRun,
  type RunEstimated,
  runEstimateQuery,
  useRunSubmission,
  useStressSubmission,
} from "@/api/runs"
import type { SavedStrategyVersion } from "@/api/strategies"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import { SchemaForm } from "@/ui/schema-form"
import { SectionFailure } from "@/ui/section-failure"
import { TextLink } from "@/ui/text-link"
import { estimateAsked, type RunDraft, runReadiness } from "./run-draft"
import { RunCostFields } from "./RunCostFields"
import { RunDataFields } from "./RunDataFields"
import { hasKeptDraft } from "./strategy-drafts"

type RunFormProps = Readonly<{
  version: SavedStrategyVersion
  draft: RunDraft
  onChange: (draft: RunDraft) => void
}>

/** The dialog's form (web/DESIGN.md, Patterns, Run backtest dialog), drawn from the estimate of
 * what the run would read, which is asked again as a choice that changes it is made. Its last
 * answer stays in view while a newer one is read, and after a refusal, so that the choice the
 * server refused can be changed back. */
export function RunForm({ version, draft, onChange }: RunFormProps) {
  const estimate = useQuery(runEstimateQuery(estimateAsked(version.id, draft)))
  const [known, setKnown] = useState<RunEstimated | null>(null)
  const answer = estimate.data
  if (answer?.state === "estimated" && answer !== known) {
    setKnown(answer)
  }
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
      latest={estimate.status === "success" && !estimate.isPlaceholderData}
      refusal={estimate.status === "error" ? estimate.error : null}
      onChange={onChange}
    />
  )
}

type FilledFormProps = RunFormProps &
  Readonly<{
    estimate: RunEstimated
    latest: boolean
    refusal: Error | null
  }>

function FilledForm({
  version,
  draft,
  estimate,
  latest,
  refusal,
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
          columns
          onChange={(parameters, entered) =>
            onChange({ ...draft, parameters, entered })
          }
        />
      </section>
      {refusal !== null && (
        <p
          role="alert"
          data-testid="run-estimate-refusal"
          className="text-negative"
        >
          {refusal.message}
        </p>
      )}
      <RunActions
        version={version}
        draft={draft}
        estimate={estimate}
        latest={latest && refusal === null}
        refused={refusal !== null}
      />
    </div>
  )
}

type RunActionsProps = Readonly<{
  version: SavedStrategyVersion
  draft: RunDraft
  estimate: RunEstimated
  latest: boolean
  refused: boolean
}>

/** What the run would read, why it waits where it does, and its two actions: Run backtest, and
 * Run with stress, which adds the same run at one and at two more ticks of slippage. A run found
 * saved opens as Cached; a run queued opens on its page, which follows its job. */
function RunActions({
  version,
  draft,
  estimate,
  latest,
  refused,
}: RunActionsProps) {
  const navigate = useNavigate()
  const submission = useRunSubmission()
  const stress = useStressSubmission()
  const readiness = runReadiness(version.id, draft, estimate, latest)
  const sending = submission.isPending || stress.isPending
  const waiting = refused
    ? "Change the choice refused above"
    : readiness.kind === "waiting"
      ? readiness.why
      : ""
  const said = sending ? "Looking the run up" : waiting
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
  return (
    <footer className="flex flex-col gap-3 border-t pt-5">
      <p data-testid="run-estimate" className="font-medium text-foreground">
        {`${counted(estimate.sessions, "session")}, ${counted(estimate.bars, "bar")}, ${counted(estimate.ticks, "tick")}`}
      </p>
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
          {said}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="ghost"
            data-testid="run-stress"
            disabled={readiness.kind === "waiting" || refused || sending}
            onClick={() => {
              if (readiness.kind === "ready") {
                stress.mutate(readiness.request, {
                  onSuccess: () =>
                    void navigate({
                      to: "/runs",
                      search: { strategy: version.name },
                      state: { stressed: version.name },
                    }),
                })
              }
            }}
          >
            Run with stress
          </Button>
          <Button
            data-testid="run-launch"
            disabled={readiness.kind === "waiting" || refused || sending}
            onClick={() => {
              if (readiness.kind === "ready") {
                submission.mutate(readiness.request, { onSuccess: open })
              }
            }}
          >
            Run backtest
          </Button>
        </div>
      </div>
    </footer>
  )
}

/** A refusal in the server's words, at its line of the code where it names one. */
function refusalWords(error: Error): string {
  return error instanceof ApiProblem && error.line !== null
    ? `Line ${error.line}: ${error.message}`
    : error.message
}
