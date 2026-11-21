import { useLocation, useNavigate } from "@tanstack/react-router"
import type { Ref } from "react"
import { ApiProblem } from "@/api/problems"
import {
  type IndexedStrategy,
  type SavedStrategyVersion,
  useStrategyValidation,
  useVersionSave,
} from "@/api/strategies"
import { Button } from "@/ui/button"
import { CodeEditor } from "@/ui/code-editor"
import { IdentityChip } from "@/ui/identity-chip"
import { formatInstant } from "@/ui/instant"
import { Panel } from "@/ui/panel"
import {
  codeLines,
  editorNotes,
  type Judged,
  type SaveRefusal,
} from "./code-notes"
import { CodeVerdict } from "./CodeVerdict"
import { type DraftState, SaveVersion } from "./SaveVersion"
import { forgetDraft, useStrategyDraft } from "./strategy-drafts"

type CodeCardProps = Readonly<{
  strategy: IndexedStrategy
  version: SavedStrategyVersion
  ref?: Ref<HTMLElement>
}>

/** A version's code in the editor (web/DESIGN.md, Patterns, Strategy page), the draft kept in this
 * browser until it is saved or discarded: Validate builds the code in the server's executor and
 * underlines its refusal at its line, the saved code shows its version's warnings, and Save as
 * new version saves the draft with its hypothesis and changelog, then opens the version saved,
 * which says so. While a save runs, Validate, which would take its answer back, and the code and
 * its words, whose changes the version it opens would drop, wait. The card takes the focus its
 * page gives it (`ref`). */
export function CodeCard({ strategy, version, ref }: CodeCardProps) {
  const { draft, change, discard, discarded, undoDiscard } = useStrategyDraft(
    strategy.name,
    version.version,
    { code: version.code, hypothesis: version.hypothesis, changelog: "" }
  )
  const validation = useStrategyValidation()
  const save = useVersionSave(strategy.id)
  const navigate = useNavigate()
  const opened = useLocation({ select: (location) => location.state.saved })
  const verdict =
    validation.status === "success"
      ? { code: validation.variables, answer: validation.data }
      : null
  const refusal = refusalAtALine(save.error, save.variables?.code)
  const lines = codeLines(draft.code, version, verdict, refusal)
  const valid =
    verdict !== null &&
    verdict.code === draft.code &&
    verdict.answer.verdict === "valid"
      ? verdict.answer
      : null
  const state = draftState(
    draft.code !== version.code,
    save.isPending,
    discarded,
    opened !== undefined &&
      opened.strategy === strategy.name &&
      opened.version === version.version
      ? version.version
      : null
  )
  const saveVersion = () => {
    validation.reset()
    save.mutate(
      {
        code: draft.code,
        hypothesis: draft.hypothesis.trim(),
        changelog: draft.changelog.trim(),
      },
      {
        onSuccess: (saved) => {
          forgetDraft(strategy.name, version.version)
          void navigate({
            to: "/strategies/strategy",
            search: { name: saved.name, version: saved.version },
            state: { saved: { strategy: saved.name, version: saved.version } },
          })
        },
      }
    )
  }
  return (
    <Panel
      ref={ref}
      tabIndex={-1}
      title="Code"
      description={`Version ${version.version} of ${strategy.versions.length}, saved ${formatInstant(version.created_at)}`}
      action={
        <IdentityChip testId="version-hash">
          {version.hash.slice(0, 12)}
        </IdentityChip>
      }
    >
      <CodeEditor
        label={`Code of ${strategy.name}`}
        code={draft.code}
        onChange={(code) => change({ ...draft, code })}
        notes={editorNotes(lines)}
        waiting={save.isPending}
      />
      <div className="flex items-baseline justify-between gap-4">
        <CodeVerdict
          lines={lines}
          valid={valid}
          validating={validation.isPending}
          failure={validation.error}
        />
        <Button
          variant="ghost"
          disabled={validation.isPending || save.isPending}
          onClick={() => {
            save.reset()
            validation.mutate(draft.code)
          }}
        >
          Validate
        </Button>
      </div>
      <SaveVersion
        draft={draft}
        state={state}
        refused={
          save.error === null ||
          refusal !== null ||
          save.variables?.code !== draft.code
            ? null
            : save.error.message
        }
        onChange={change}
        onDiscard={discard}
        onUndoDiscard={undoDiscard}
        onSave={saveVersion}
      />
    </Panel>
  )
}

/** Where the draft stands: saving, edited, just discarded, the version a save just opened,
 * `opened`, or the version's own code. */
function draftState(
  edited: boolean,
  saving: boolean,
  discarded: boolean,
  opened: number | null
): DraftState {
  if (saving) {
    return { kind: "saving" }
  }
  if (edited) {
    return { kind: "edited" }
  }
  if (discarded) {
    return { kind: "discarded" }
  }
  return opened === null
    ? { kind: "unchanged" }
    : { kind: "saved", version: opened }
}

/** A save the SDK refused at a line of the code it was given, which the editor underlines; a
 * refusal of the words, such as a hypothesis on two lines, or another failure, names no line and
 * stands by the button instead. */
function refusalAtALine(
  error: Error | null,
  code: string | undefined
): Judged<SaveRefusal> | null {
  if (
    !(error instanceof ApiProblem) ||
    error.line === null ||
    code === undefined
  ) {
    return null
  }
  return { code, answer: { line: error.line, message: error.message } }
}
