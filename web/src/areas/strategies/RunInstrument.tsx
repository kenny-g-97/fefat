import { IdentityChip } from "@/ui/identity-chip"
import { Choice, Picker } from "@/ui/picker"
import {
  chosenInstrument,
  instrumentChoices,
  instrumentChosen,
  type RunDraft,
} from "./run-draft"

type RunInstrumentProps = Readonly<{
  draft: RunDraft
  held: readonly string[]
  own: string
  onChange: (draft: RunDraft) => void
}>

/** The instrument the run trades (web/DESIGN.md, Patterns, Run backtest dialog): a select of those
 * the store holds, with the one the code names, `own`, which stays the default; or that one in
 * its identity chip, where there is nothing else to choose. */
export function RunInstrument({
  draft,
  held,
  own,
  onChange,
}: RunInstrumentProps) {
  const chosen = chosenInstrument(draft, own)
  const choices = instrumentChoices(held, own, chosen)
  if (choices.length === 1) {
    return (
      <OnlyChoice label="Instrument" testId="run-instrument">
        {chosen}
      </OnlyChoice>
    )
  }
  return (
    <Choice id="run-instrument" label="Instrument">
      <Picker
        id="run-instrument"
        className="w-full"
        value={chosen}
        options={choices.map((each) => ({ value: each, label: each }))}
        onChange={(next) => onChange(instrumentChosen(draft, next, own))}
      />
    </Choice>
  )
}

/** A field with nothing to choose among: its label over what it holds, in an identity chip. */
export function OnlyChoice({
  label,
  testId,
  children,
}: Readonly<{ label: string; testId: string; children: string }>) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm leading-none font-medium text-foreground">
        {label}
      </span>
      <span className="flex h-10 items-center">
        <IdentityChip testId={testId}>{children}</IdentityChip>
      </span>
    </div>
  )
}
