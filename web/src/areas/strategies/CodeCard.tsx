import { useNavigate } from "@tanstack/react-router"
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
import { SaveVersion } from "./SaveVersion"
import { forgetDraft, useStrategyDraft } from "./strategy-drafts"

type CodeCardProps = Readonly<{
  strategy: IndexedStrategy
  version: SavedStrategyVersion
}>

/** A version's code in the editor (web/DESIGN.md, Patterns, Strategy page), the draft kept in this
 * browser until it is saved or discarded: Validate builds the code in the server's executor and
 * underlines its refusal at its line, the saved code shows its version's warnings, and Save as
 * new version saves the draft with its hypothesis and changelog, then opens the version saved. */
export function CodeCard({ strategy, version }: CodeCardProps) {
  const { draft, change, discard } = useStrategyDraft(
    strategy.name,
    version.version,
    { code: version.code, hypothesis: version.hypothesis, changelog: "" }
  )
  const validation = useStrategyValidation()
  const save = useVersionSave(strategy.id)
  const navigate = useNavigate()
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
          })
        },
      }
    )
  }
  return (
    <Panel
      title="Code"
      description={`Version ${version.version}, saved ${formatInstant(version.created_at)}`}
      action={
        <IdentityChip testId="version-hash">
          {version.hash.slice(0, 12)}
        </IdentityChip>
      }
    >
      <div className="flex flex-col gap-3">
        <CodeEditor
          label={`Code of ${strategy.name}`}
          code={draft.code}
          onChange={(code) => change({ ...draft, code })}
          notes={editorNotes(lines)}
        />
        <p className="text-xs text-muted-foreground">
          Tab indents. Press Escape, then Tab, to leave the editor.
        </p>
      </div>
      <div className="flex items-start justify-between gap-4">
        <CodeVerdict
          lines={lines}
          valid={valid}
          validating={validation.isPending}
          failure={validation.error}
        />
        <Button
          variant="ghost"
          disabled={validation.isPending}
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
        edited={draft.code !== version.code}
        saving={save.isPending}
        refused={
          save.error === null || refusal !== null ? null : save.error.message
        }
        onChange={change}
        onDiscard={discard}
        onSave={saveVersion}
      />
    </Panel>
  )
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
