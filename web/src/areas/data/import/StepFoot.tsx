import type { MouseEvent } from "react"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import type { Draft } from "./import-draft"
import type { ImportRun } from "./import-run"
import { type Step, STEP_NAMES, stepAfter, stepBefore } from "./import-steps"

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
            <ImportWaits run={run} reason={reason} />
            <Button
              key="import"
              data-testid="import-run"
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

/** Beside Import: the server's refusal of the import while the draft is the one refused, else
 * why Import waits. */
function ImportWaits({
  run,
  reason,
}: Readonly<{ run: ImportRun; reason: string | null }>) {
  if (run.refusal !== null) {
    return (
      <p role="alert" className="text-negative">
        {run.refusal.message}
      </p>
    )
  }
  return reason === null ? null : (
    <p className="text-foreground-secondary" data-testid="import-waits">
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
