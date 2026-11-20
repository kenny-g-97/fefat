import { type FormEvent, useRef, useState } from "react"
import { Button } from "@/ui/button"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import { Input } from "@/ui/input"
import { Label } from "@/ui/label"
import type { StrategyDraft } from "./strategy-drafts"

type SaveVersionProps = Readonly<{
  draft: StrategyDraft
  edited: boolean
  saving: boolean
  refused: string | null
  onChange: (draft: StrategyDraft) => void
  onDiscard: () => void
  onSave: () => void
}>

const FORM = "save-version"

/** Save as new version, under the editor in the code's card (web/DESIGN.md, Patterns, Strategy
 * page): the hypothesis, one sentence stating the edge (D-29), and the changelog, the draft's
 * words, kept with its code in the browser, so they live in the draft rather than in
 * react-hook-form, as the import wizard's fields do; Discard draft, asked once in place, since
 * typed code cannot be brought back; and the save, which waits while the code is the version's,
 * saying so, and while it runs. A refusal that names no line of the code stands under it. */
export function SaveVersion({
  draft,
  edited,
  saving,
  refused,
  onChange,
  onDiscard,
  onSave,
}: SaveVersionProps) {
  const [missing, setMissing] = useState(false)
  const hypothesis = useRef<HTMLInputElement>(null)
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
            onChange={(event) =>
              onChange({ ...draft, changelog: event.target.value })
            }
          />
        </div>
      </form>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <p
          data-testid="draft-state"
          className="mr-auto text-xs text-muted-foreground"
        >
          {draftState(edited, saving)}
        </p>
        {edited && !saving && (
          <InlineConfirmation
            trigger="Discard draft"
            confirm="Discard"
            size="default"
            onConfirm={onDiscard}
          />
        )}
        <Button type="submit" form={FORM} disabled={!edited || saving}>
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

function draftState(edited: boolean, saving: boolean): string {
  if (saving) {
    return "Saving"
  }
  return edited
    ? "Draft, not saved"
    : "Change the code to save it as a new version"
}
