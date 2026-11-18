import { type MouseEvent, useId } from "react"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import type { Draft } from "./import-draft"
import type { ImportRun } from "./import-run"
import type { Step } from "./import-search"
import { STEP_NAMES, stepAfter, stepBefore } from "./import-steps"

type StepFootProps = Readonly<{
  draft: Draft
  shown: Step
  onStep: (step: Step) => void
  run: ImportRun
  reason: string | null
  importing: number | null
}>

/** Under the card shown (web/DESIGN.md, Patterns, Import wizard; D-105): Back, named for the
 * step it opens, at the left; Continue at the right, which never waits; and on the last step
 * Import in its place, named for what it sends, with why it waits beside it, or the server's
 * refusal. Import is a button of its own, so that the focus never carries over from Continue,
 * and each ignores the second click of a double click, which would otherwise press Import
 * where Continue stood, or skip a step. */
export function StepFoot({
  draft,
  shown,
  onStep,
  run,
  reason,
  importing,
}: StepFootProps) {
  const before = stepBefore(shown, draft)
  const after = stepAfter(shown, draft)
  const waits = useId()
  return (
    <div className="flex flex-wrap items-center gap-4">
      {before !== null && (
        <Button
          key={`back ${before}`}
          variant="ghost"
          data-testid="step-back"
          onClick={firstClick(() => onStep(before))}
        >
          {`Back to ${STEP_NAMES[before]}`}
        </Button>
      )}
      <div className="ml-auto flex flex-wrap items-center justify-end gap-4">
        {after !== null ? (
          <Button
            key="continue"
            data-testid="step-continue"
            onClick={firstClick(() => onStep(after))}
          >
            Continue
          </Button>
        ) : (
          <>
            <ImportWaits id={waits} run={run} reason={reason} />
            <Button
              key="import"
              data-testid="import-run"
              aria-describedby={
                run.refusal !== null || reason !== null ? waits : undefined
              }
              disabled={!run.importable}
              onClick={firstClick(run.importNow)}
            >
              {importing === null
                ? "Import"
                : `Import ${counted(importing, "file")}`}
            </Button>
          </>
        )}
      </div>
    </div>
  )
}

/** Beside Import, which it describes: the server's refusal of the import while the draft is
 * the one refused, else why Import waits. */
function ImportWaits({
  id,
  run,
  reason,
}: Readonly<{ id: string; run: ImportRun; reason: string | null }>) {
  if (run.refusal !== null) {
    return (
      <p id={id} role="alert" className="text-negative">
        {run.refusal.message}
      </p>
    )
  }
  return reason === null ? null : (
    <p id={id} className="text-foreground-secondary" data-testid="import-waits">
      {reason}
    </p>
  )
}

/** A press that acts on the first click alone, the keyboard's included, whose click counts
 * none. */
function firstClick(act: () => void) {
  return (event: MouseEvent) => {
    if (event.detail <= 1) {
      act()
    }
  }
}
