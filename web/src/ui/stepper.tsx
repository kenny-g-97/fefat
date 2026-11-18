import { cn } from "cn"
import { Check } from "lucide-react"

/** What the list says of a step: that the work in hand does not need it, that it is complete,
 * with what was chosen, or what it still needs, an alert where a later step points back at it. */
export type StepState =
  | Readonly<{ kind: "not needed"; line: string }>
  | Readonly<{ kind: "complete"; line: string }>
  | Readonly<{ kind: "incomplete"; line: string; alert: boolean }>

export type StepperStep<Id extends string> = Readonly<{
  id: Id
  name: string
  state: StepState
}>

type StepperProps<Id extends string> = Readonly<{
  label: string
  steps: readonly StepperStep<Id>[]
  current: Id
  onStep: (id: Id) => void
}>

/** A task's steps down the left of its page (web/DESIGN.md, Patterns, Stepper): each a button
 * that opens its step, its number or, once complete, a check in a tile, its name, and one line
 * of what it needs or what was chosen; the current one in the active item's soft fill, as the
 * sidebar marks its page, and a step not needed disabled. */
export function Stepper<Id extends string>({
  label,
  steps,
  current,
  onStep,
}: StepperProps<Id>) {
  return (
    <nav aria-label={label} className="w-56 shrink-0">
      <ol className="flex flex-col gap-1">
        {steps.map((step, index) => (
          <li key={step.id}>
            <StepRow
              step={step}
              number={index + 1}
              current={step.id === current}
              onPress={() => onStep(step.id)}
            />
          </li>
        ))}
      </ol>
    </nav>
  )
}

type StepRowProps = Readonly<{
  step: StepperStep<string>
  number: number
  current: boolean
  onPress: () => void
}>

function StepRow({ step, number, current, onPress }: StepRowProps) {
  const state = step.state
  return (
    <button
      type="button"
      data-testid={`step-${step.id}`}
      data-state={state.kind}
      aria-current={current ? "step" : undefined}
      disabled={state.kind === "not needed"}
      onClick={onPress}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl border p-2 text-left disabled:opacity-50",
        current
          ? "border-brand-soft-border bg-brand-soft"
          : "border-transparent hover:border-border hover:bg-muted"
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-xl text-xs font-semibold",
          current
            ? "bg-brand-soft-border text-brand-soft-foreground"
            : "bg-accent text-foreground"
        )}
      >
        {state.kind === "complete" ? <Check className="size-4" /> : number}
      </span>
      <span className="flex min-w-0 flex-col">
        <span
          className={cn(
            "font-medium",
            current ? "text-brand-soft-foreground" : "text-foreground"
          )}
        >
          {step.name}
          <span className="sr-only">{markOf(state)}</span>
        </span>
        <span className={cn("text-xs", lineTone(state, current))}>
          {state.line}
        </span>
      </span>
    </button>
  )
}

/** What a screen reader hears after the step's name, which the tile shows by its check. */
function markOf(state: StepState): string {
  switch (state.kind) {
    case "not needed":
      return ""
    case "complete":
      return ", complete"
    case "incomplete":
      return ", not complete"
  }
}

/** The line's colour: the negative for an alert; else body text on the current step, where
 * subtle text would fall to 4.5 : 1 on the soft fill, and subtle text elsewhere. */
function lineTone(state: StepState, current: boolean): string {
  if (state.kind === "incomplete" && state.alert) {
    return "text-negative"
  }
  return current ? "text-foreground-secondary" : "text-muted-foreground"
}
