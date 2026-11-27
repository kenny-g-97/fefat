import { X } from "lucide-react"
import { useId } from "react"
import type { ExplainedEvent } from "@/api/explanations"
import type { Trade } from "@/api/trades"
import { Button } from "@/ui/button"
import { counted, fidelityLabel, sentenceCase } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { formatInstantToTheSecond } from "@/ui/instant"
import { PercentBar } from "@/ui/percent-bar"
import type { ExplanationState } from "./explanation-run"

type ExplanationPanelProps = Readonly<{
  trade: Trade
  state: ExplanationState
  onClose: () => void
  onExplainAgain: () => void
}>

/** A trade's explanation beside the chart (web/DESIGN.md, Patterns, Explanation panel): the
 * trade it explains, then while its job runs its bar and message, once answered the replay's
 * events in the order they happened as a timeline, each its instant to the second, what
 * happened, its words, and its rule in an identity chip, or the replay's refusal as a sentence;
 * a job that failed says why, with Explain again. */
export function ExplanationPanel({
  trade,
  state,
  onClose,
  onExplainAgain,
}: ExplanationPanelProps) {
  const heading = useId()
  // As tall as the chart beside it, whatever its timeline holds, which scrolls inside it.
  return (
    <div className="relative w-96 shrink-0">
      <section
        aria-labelledby={heading}
        data-testid="explanation-panel"
        className="absolute inset-0 flex flex-col gap-4 overflow-hidden rounded-xl border bg-card p-6 shadow-raised"
      >
        <header className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id={heading} className="text-base font-semibold">
              Explanation
            </h2>
            <p className="text-foreground-secondary">
              {`${sentenceCase(trade.side)} ${counted(trade.lots, "lot")}, entered `}
              <span className="whitespace-nowrap">
                {formatInstantToTheSecond(trade.entry_ts)}
              </span>
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon-lg"
            aria-label="Close the explanation"
            onClick={onClose}
            className="-my-2 -mr-2"
          >
            <X className="size-5" aria-hidden="true" />
          </Button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <ExplanationBody state={state} onExplainAgain={onExplainAgain} />
        </div>
      </section>
    </div>
  )
}

function ExplanationBody({
  state,
  onExplainAgain,
}: Readonly<{ state: ExplanationState; onExplainAgain: () => void }>) {
  if (state.kind === "starting") {
    return <p className="text-xs text-muted-foreground">Queueing the replay</p>
  }
  if (state.kind === "running") {
    return (
      <div className="flex flex-col gap-2" data-testid="explanation-running">
        <PercentBar value={state.job.progress} label="Replay of the trade" />
        <p className="text-xs text-muted-foreground">
          {state.job.message === null ? "Queued" : state.job.message}
        </p>
      </div>
    )
  }
  if (state.kind === "failed") {
    return (
      <div className="flex flex-col items-start gap-3">
        <p role="alert" className="text-negative">
          {state.message}
        </p>
        <Button variant="ghost" onClick={onExplainAgain}>
          Explain again
        </Button>
      </div>
    )
  }
  const { explanation } = state
  if (explanation.kind === "refused") {
    return (
      <p
        data-testid="explanation-refused"
        className="text-foreground-secondary"
      >
        {explanation.reason}
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        {`Replayed through the reference engine from ${formatInstantToTheSecond(explanation.started_at)}, on ${fidelityWords(explanation.fills)}`}
      </p>
      <ol aria-label="Events of the replay" className="flex flex-col">
        {explanation.events.map((event, index) => (
          <EventRow key={`${event.time} ${index}`} event={event} />
        ))}
      </ol>
    </div>
  )
}

/** What the replay's records were, by the fidelity its fills priced on, one for every fill of an
 * episode the replay takes: `trades`, or `1-minute bars`. */
function fidelityWords(
  fills: readonly Readonly<{ fidelity: string }>[]
): string {
  const first = fills.at(0)
  return first === undefined
    ? "the run's records"
    : fidelityLabel(first.fidelity).toLowerCase()
}

function EventRow({ event }: Readonly<{ event: ExplainedEvent }>) {
  return (
    <li
      data-testid="explained-event"
      data-kind={event.kind}
      className="flex flex-col gap-1 border-b py-3 last:border-b-0"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-foreground">
          {sentenceCase(event.kind)}
        </span>
        <span
          data-testid="explained-event-time"
          className="text-xs text-muted-foreground"
        >
          {formatInstantToTheSecond(event.time)}
        </span>
      </div>
      <p className="text-foreground-secondary">{event.text}</p>
      {event.rule !== null && (
        <span>
          <IdentityChip>{event.rule}</IdentityChip>
        </span>
      )}
    </li>
  )
}
