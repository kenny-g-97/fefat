import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { ApiProblem, isRefusal } from "@/api/problems"
import {
  type ListedRun,
  type NoDataToEstimate,
  type RunEstimateAnswer,
  type RunEstimated,
  type RunSubmission,
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
  estimateWords,
  instrumentChoices,
  type RunDraft,
  type RunReadiness,
  runReadiness,
  stressedSearch,
} from "./run-draft"
import { RunCostFields } from "./RunCostFields"
import { RunDataFields } from "./RunDataFields"
import { RunInstrument } from "./RunInstrument"
import { hasKeptDraft } from "./strategy-drafts"

type RunFormProps = Readonly<{
  version: SavedStrategyVersion
  draft: RunDraft
  lastAnswer: RunEstimateAnswer | null
  onAnswered: (answer: RunEstimateAnswer) => void
  onChange: (draft: RunDraft) => void
}>

/** The dialog's form (web/DESIGN.md, Patterns, Run backtest dialog), drawn from the estimate of
 * what the run would read, which is asked again as a choice that changes it is made. Its last
 * answer, which the dialog keeps for a form opened again, stays in view while a newer one is
 * read, and after a refusal, so that the choice the server refused can be changed back. */
export function RunForm({
  version,
  draft,
  lastAnswer,
  onAnswered,
  onChange,
}: RunFormProps) {
  const estimate = useQuery(runEstimateQuery(estimateAsked(version.id, draft)))
  const answer = estimate.data
  useEffect(() => {
    if (answer !== undefined) {
      onAnswered(answer)
    }
  }, [answer, onAnswered])
  const known = answer === undefined ? lastAnswer : answer
  const failure = estimate.status === "error" ? estimate.error : null
  const onRetry = () => void estimate.refetch()
  if (known === null) {
    return failure === null ? (
      <p role="status" className="min-h-24 text-foreground-secondary">
        Counting what this run would read
      </p>
    ) : (
      <SectionFailure error={failure} onRetry={onRetry} />
    )
  }
  if (known.state === "no_data") {
    return (
      <NoDataOfTheInstrument
        answer={known}
        reading={estimate.status === "pending"}
        failure={failure}
        onRetry={onRetry}
        own={version.instrument}
        draft={draft}
        onChange={onChange}
      />
    )
  }
  return (
    <FilledForm
      version={version}
      draft={draft}
      estimate={known}
      latest={estimate.status === "success" && !estimate.isFetching}
      failure={failure}
      onRetry={onRetry}
      onChange={onChange}
    />
  )
}

/** The form's first field takes the focus once it is drawn (web/DESIGN.md, Patterns, Dialog). */
function useFirstFieldFocused() {
  const form = useRef<HTMLDivElement>(null)
  useEffect(() => {
    form.current?.querySelector<HTMLElement>("input, button")?.focus()
  }, [])
  return form
}

/** Where the store holds none of the instrument: one sentence over a link to Import data, and,
 * where it holds another, the field that chooses it, so that a template written for one market
 * can run on the market a trader has. The field stays while its next choice is read, and after a
 * refusal, so that the choice can be changed back. */
function NoDataOfTheInstrument({
  answer,
  reading,
  failure,
  onRetry,
  own,
  draft,
  onChange,
}: Readonly<{
  answer: NoDataToEstimate
  reading: boolean
  failure: Error | null
  onRetry: () => void
  own: string
  draft: RunDraft
  onChange: (draft: RunDraft) => void
}>) {
  const form = useFirstFieldFocused()
  const chosen = draft.instrument === null ? own : draft.instrument
  const canChoose =
    instrumentChoices(answer.instruments, own, chosen).length > 1
  const wayOut =
    answer.instruments.length > 0
      ? `Choose one it holds, or import ${answer.instrument}'s bars or ticks.`
      : "Import its bars or ticks, then run this strategy."
  return (
    <div ref={form} className="flex flex-col items-start gap-3">
      {canChoose && (
        <div className="grid w-full grid-cols-3 gap-4">
          <RunInstrument
            draft={draft}
            held={answer.instruments}
            own={own}
            onChange={onChange}
          />
        </div>
      )}
      {failure !== null ? (
        <SectionFailure error={failure} onRetry={onRetry} />
      ) : reading ? (
        <p role="status" className="text-foreground-secondary">
          Counting what this run would read
        </p>
      ) : (
        <>
          <p role="alert" className="text-foreground-secondary">
            {`FEAT holds no data of ${answer.instrument}. ${wayOut}`}
          </p>
          <TextLink to="/data/import">Import data</TextLink>
        </>
      )}
    </div>
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
  const form = useFirstFieldFocused()
  return (
    <div ref={form} className="flex flex-col gap-5">
      {draftKept && (
        <p data-testid="run-draft-note" className="text-foreground-secondary">
          {`Your draft is not saved: this runs version ${version.version} as saved.`}
        </p>
      )}
      <RunDataFields
        draft={draft}
        estimate={estimate}
        own={version.instrument}
        onChange={onChange}
      />
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
      <RunActions
        version={version}
        draft={draft}
        estimate={estimate}
        latest={latest}
        failure={failure}
        onRetry={onRetry}
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
  onRetry: () => void
}>

/** Which of the two actions a press asked for. */
type Launch = "run" | "stress"

/** What the run would read, why it waits where it does, and its two actions: Run backtest, and
 * Run with stress, which adds the same run at one and at two more ticks of slippage. A run found
 * saved opens as Cached; a run queued opens on its page, which follows its job. A press while the
 * estimate is read, as leaving a typed date by pressing makes it, is kept until its answer, and
 * given up for good if the draft changes, the estimate fails or makes the run wait, or the dialog
 * closes, so that no later read launches a run nobody pressed for. */
function RunActions({
  version,
  draft,
  estimate,
  latest,
  failure,
  onRetry,
}: RunActionsProps) {
  const navigate = useNavigate()
  const submission = useRunSubmission()
  const stress = useStressSubmission()
  const [held, setHeld] = useState<Readonly<{
    launch: Launch
    draft: RunDraft
  }> | null>(null)
  const sent = useRef<typeof held>(null)
  const readiness = runReadiness(version.id, draft, estimate, latest)
  const kept =
    held !== null &&
    held.draft === draft &&
    failure === null &&
    readiness.kind !== "waiting"
      ? held
      : null
  if (held !== null && kept === null) {
    setHeld(null)
  }
  const holding = kept !== null && readiness.kind === "reading"
  const sending = submission.isPending || stress.isPending || holding
  const closed = failure !== null || readiness.kind === "waiting" || sending
  const failed = submission.error ?? stress.error
  const open = (run: ListedRun) =>
    void navigate(
      run.state === "saved"
        ? {
            to: "/runs/run",
            search: { key: run.run_key },
            state: { cachedRun: run.run_key, askedVersion: version.id },
          }
        : {
            to: "/runs/run",
            search: { id: run.id, job: run.job_id },
            state: { askedVersion: version.id },
          }
    )
  const send = (launch: Launch, request: RunSubmission) => {
    const onSettled = () => setHeld(null)
    if (launch === "run") {
      stress.reset()
      submission.mutate(request, { onSuccess: open, onSettled })
      return
    }
    submission.reset()
    stress.mutate(request, {
      onSuccess: ({ runs }) =>
        void navigate({
          to: "/runs",
          search: stressedSearch(runs, version.name),
          state: { stressed: version.name },
        }),
      onSettled,
    })
  }
  const press = (launch: Launch) => {
    if (readiness.kind === "ready") {
      send(launch, readiness.request)
    } else {
      setHeld({ launch, draft })
    }
  }
  useEffect(() => {
    if (kept !== null && readiness.kind === "ready" && sent.current !== kept) {
      sent.current = kept
      send(kept.launch, readiness.request)
    }
  })
  return (
    <footer className="sticky -bottom-6 -mx-6 -mb-6 flex flex-col gap-3 border-t bg-card px-6 pt-5 pb-6">
      <div className="flex flex-col gap-1">
        <p data-testid="run-estimate" className="font-medium text-foreground">
          {estimateWords(estimate, version.instrument)}
        </p>
        <p
          data-testid="run-stress-note"
          className="text-xs text-muted-foreground"
        >
          Run with stress also runs it at 1 and at 2 more ticks of slippage
        </p>
      </div>
      {failure !== null && (
        <EstimateFailure failure={failure} onRetry={onRetry} />
      )}
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
            onClick={() => press("stress")}
          >
            Run with stress
          </Button>
          <Button
            data-testid="run-launch"
            disabled={closed}
            onClick={() => press("run")}
          >
            Run backtest
          </Button>
        </div>
      </div>
    </footer>
  )
}

/** An estimate that did not answer, in the pinned foot, which would otherwise cover it: a refusal
 * in the server's words, or a failure with Try again. */
function EstimateFailure({
  failure,
  onRetry,
}: Readonly<{ failure: Error; onRetry: () => void }>) {
  return isRefusal(failure, 400) ? (
    <p
      role="alert"
      data-testid="run-estimate-refusal"
      className="text-negative wrap-anywhere"
    >
      {failure.message}
    </p>
  ) : (
    <SectionFailure error={failure} onRetry={onRetry} />
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
