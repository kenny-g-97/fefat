import type { Dispatch } from "react"
import { Button } from "@/ui/button"
import { Decision, Options } from "./Decision"
import { useFocusAfterPress } from "./focus-after-press"
import {
  decisionWords,
  type RoundDecision,
  roundDecisions,
  skipAction,
} from "./import-decisions"
import type { Draft, DraftChange } from "./import-draft"
import type { ReviewedFile } from "./import-round"

/** Each kind's box, by its test id. */
const TEST_IDS: Readonly<Record<RoundDecision["problem"], string>> = {
  "bars in breaks": "decision-bars",
  differing: "decision-differing",
  "not correctable": "decision-other",
}

type RoundDecisionsProps = Readonly<{
  files: readonly ReviewedFile[]
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** Under a round's rows, once each file is read (web/DESIGN.md, Patterns, Review; D-106): a
 * box for each kind of problem the round's files share, bars in a break, then records that
 * differ, then the files no correction fits, each answered once for every file of its kind. */
export function RoundDecisions({ files, draft, change }: RoundDecisionsProps) {
  return roundDecisions(files, draft).map((decision) => {
    const words = decisionWords(decision)
    const testId = TEST_IDS[decision.problem]
    const problem = decision.problem
    if (problem === "not correctable") {
      return (
        <Decision
          key={problem}
          title={words.title}
          message={words.message}
          notes={words.notes}
          testId={testId}
        >
          <SkipAll decision={decision} draft={draft} change={change} />
        </Decision>
      )
    }
    return (
      <Decision
        key={problem}
        title={words.title}
        message={words.message}
        notes={words.notes}
        testId={testId}
      >
        <Options
          label={words.title}
          options={words.options.map(({ answer, label, description }) => ({
            value: answer,
            label,
            description,
          }))}
          value={decision.answer}
          onChange={(answer) =>
            change({
              kind: "decided",
              problem,
              files: decision.files,
              answer,
            })
          }
          testId={`${testId}-options`}
        />
      </Decision>
    )
  })
}

type SkipAllProps = Readonly<{
  decision: RoundDecision
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** The one action of the box of the files no correction fits: Skip for those not skipped yet,
 * then the way back for them all, each taking the focus from the other it replaces. A skip asks
 * for no confirmation, since it writes nothing and one click takes it back. */
function SkipAll({ decision, draft, change }: SkipAllProps) {
  const [button, focusNext] = useFocusAfterPress()
  const kept = decision.files.filter((file) => !draft.skipped.includes(file))
  return (
    <Button
      key={kept.length > 0 ? "skip" : "do not skip"}
      ref={button}
      variant="ghost"
      size="sm"
      className="self-start"
      onClick={() => {
        focusNext()
        change({
          kind: "skipped",
          files:
            kept.length > 0
              ? [...draft.skipped, ...kept]
              : draft.skipped.filter((file) => !decision.files.includes(file)),
        })
      }}
    >
      {skipAction(decision)}
    </Button>
  )
}
