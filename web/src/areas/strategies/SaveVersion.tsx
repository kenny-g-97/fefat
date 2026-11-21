import { type FormEvent, useEffect, useRef, useState } from "react"
import { Button } from "@/ui/button"
import { Input } from "@/ui/input"
import { Label } from "@/ui/label"
import type { StrategyDraft } from "./strategy-drafts"

/** Where the draft stands, which the line before the buttons says. */
export type DraftState =
  | Readonly<{ kind: "saving" }>
  | Readonly<{ kind: "edited" }>
  | Readonly<{ kind: "discarded" }>
  | Readonly<{ kind: "saved"; version: number }>
  | Readonly<{ kind: "unchanged" }>

type SaveVersionProps = Readonly<{
  draft: StrategyDraft
  state: DraftState
  refused: string | null
  onChange: (draft: StrategyDraft) => void
  onDiscard: () => void
  onUndoDiscard: () => void
  onSave: () => void
}>

const FORM = "save-version"

/** Save as new version, under the editor in the code's card (web/DESIGN.md, Patterns, Strategy
 * page): the hypothesis, one sentence stating the edge (D-29), and the changelog, the draft's
 * words, kept with its code in the browser, so they live in the draft rather than in
 * react-hook-form, as the import wizard's fields do; Discard draft, which acts at once and gives
 * way to Undo discard until the next change, in the same button, so that the focus stays on it;
 * and the save, which waits while the code is the version's, saying so, and while it runs, as the
 * words do then. A refusal that names no line of the code stands under it. */
export function SaveVersion({
  draft,
  state,
  refused,
  onChange,
  onDiscard,
  onUndoDiscard,
  onSave,
}: SaveVersionProps) {
  const [missing, setMissing] = useState(false)
  const hypothesis = useRef<HTMLInputElement>(null)
  const saving = state.kind === "saving"
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (draft.hypothesis.trim() === "") {
      setMissing(true)
      hypothesis.current?.focus()
      return
    }
    onSave()
  }
  return (
    <div className="flex flex-col gap-5 border-t pt-5">
      <form
        id={FORM}
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-5"
      >
        <div className="flex flex-col gap-2">
          <Label
            htmlFor="version-hypothesis"
            className={missing ? "text-negative" : undefined}
          >
            Hypothesis
          </Label>
          <Input
            ref={hypothesis}
            id="version-hypothesis"
            value={draft.hypothesis}
            autoComplete="off"
            disabled={saving}
            aria-invalid={missing}
            aria-describedby="version-hypothesis-note"
            onChange={(event) => {
              setMissing(false)
              onChange({ ...draft, hypothesis: event.target.value })
            }}
          />
          <p
            id="version-hypothesis-note"
            className={
              missing ? "text-negative" : "text-xs text-muted-foreground"
            }
          >
            {missing
              ? "Write the hypothesis, one sentence stating the edge."
              : "One sentence stating the edge, which the page shows above the code"}
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="version-changelog">Changelog</Label>
          <Input
            id="version-changelog"
            value={draft.changelog}
            placeholder="What changed, such as a wider stop"
            autoComplete="off"
            disabled={saving}
            onChange={(event) =>
              onChange({ ...draft, changelog: event.target.value })
            }
          />
        </div>
      </form>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <DraftLine state={state} />
        {(state.kind === "edited" || state.kind === "discarded") && (
          <Button
            variant="ghost"
            onClick={state.kind === "edited" ? onDiscard : onUndoDiscard}
          >
            {state.kind === "edited" ? "Discard draft" : "Undo discard"}
          </Button>
        )}
        <Button type="submit" form={FORM} disabled={state.kind !== "edited"}>
          Save as new version
        </Button>
      </div>
      {refused !== null && (
        <p role="alert" className="text-negative">
          {refused}
        </p>
      )}
    </div>
  )
}

const DRAFT_LINES: Readonly<
  Record<Exclude<DraftState["kind"], "saved">, string>
> = {
  saving: "Saving",
  edited: "Draft, not saved",
  discarded: "Draft discarded",
  unchanged: "Change the code to save it as a new version",
}

/** The draft's state before the buttons, in a status region; a version a save just opened says
 * so and takes the focus once, on arrival, so that a screen reader hears it, as the Data page's
 * line after a delete does, and a change taken back later leaves the focus where it is. */
function DraftLine({ state }: Readonly<{ state: DraftState }>) {
  const line = useRef<HTMLParagraphElement>(null)
  const announced = useRef(false)
  const saved = state.kind === "saved"
  useEffect(() => {
    if (saved && !announced.current) {
      announced.current = true
      line.current?.focus()
    }
  }, [saved])
  return (
    <p
      ref={line}
      role="status"
      tabIndex={saved ? -1 : undefined}
      data-testid="draft-state"
      className={
        saved
          ? "mr-auto text-foreground-secondary"
          : "mr-auto text-xs text-muted-foreground"
      }
    >
      {state.kind === "saved"
        ? `Saved as version ${state.version}.`
        : DRAFT_LINES[state.kind]}
    </p>
  )
}
