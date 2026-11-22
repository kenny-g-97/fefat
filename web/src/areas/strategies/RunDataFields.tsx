import type { RunEstimated } from "@/api/runs"
import { Button } from "@/ui/button"
import { IdentityChip } from "@/ui/identity-chip"
import { KeptField } from "@/ui/kept-field"
import { Choice, Picker } from "@/ui/picker"
import {
  type RunDraft,
  shownDates,
  tradeDateRefusal,
  windowRefusal,
} from "./run-draft"

/** The contract select's first choice: the roll calendar's fronts. No contract name holds
 * parentheses. */
const SPLICED = "(spliced)"

type RunDataFieldsProps = Readonly<{
  draft: RunDraft
  estimate: RunEstimated
  onChange: (draft: RunDraft) => void
}>

/** Which data the run reads: the provider, where several hold the instrument, the contract, and
 * the trade dates, typed and checked against what the data holds, never read through the
 * browser's clock (`run-draft.ts`). */
export function RunDataFields({
  draft,
  estimate,
  onChange,
}: RunDataFieldsProps) {
  const { providers, contracts, settings } = estimate
  return (
    <>
      <div className="grid grid-cols-2 gap-4">
        {providers.length > 1 ? (
          <Choice id="run-provider" label="Data">
            <Picker
              id="run-provider"
              className="w-full"
              value={settings.provider}
              options={providers.map((each) => ({ value: each, label: each }))}
              onChange={(provider) =>
                onChange({ ...draft, provider, contract: null })
              }
            />
          </Choice>
        ) : (
          <div className="flex flex-col gap-2">
            <span className="text-sm leading-none font-medium text-foreground">
              Data
            </span>
            <span className="flex h-10 items-center">
              <IdentityChip testId="run-provider">
                {settings.provider}
              </IdentityChip>
            </span>
          </div>
        )}
        {contracts.length > 0 && (
          <Choice id="run-contract" label="Contract">
            <Picker
              id="run-contract"
              className="w-full"
              value={draft.contract === null ? SPLICED : draft.contract}
              options={[
                { value: SPLICED, label: "Spliced" },
                ...contracts.map((each) => ({ value: each, label: each })),
              ]}
              onChange={(chosen) =>
                onChange({
                  ...draft,
                  contract: chosen === SPLICED ? null : chosen,
                })
              }
            />
          </Choice>
        )}
      </div>
      <RunDates draft={draft} estimate={estimate} onChange={onChange} />
    </>
  )
}

function RunDates({ draft, estimate, onChange }: RunDataFieldsProps) {
  const { held } = estimate
  const dates = shownDates(draft, estimate)
  // The estimate's own contract: its dates are that series', while a newer answer is read too.
  const applied = estimate.settings.contract
  const series = applied === null ? estimate.instrument : applied
  if (held === null || dates === null) {
    return (
      <p role="alert" data-testid="run-coverage" className="text-negative">
        {`${estimate.settings.provider} holds no bars of ${series} that build ${estimate.timeframe} bars. Choose other data.`}
      </p>
    )
  }
  const fromRefusal = tradeDateRefusal(dates.from, held)
  const toRefusal =
    tradeDateRefusal(dates.to, held) ?? windowRefusal(dates.from, dates.to)
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-[1fr_1fr_auto] items-start gap-4">
        <Choice id="run-from" label="From" refusal={fromRefusal}>
          <KeptField
            id="run-from"
            value={dates.from}
            invalid={fromRefusal !== null}
            describedBy={fromRefusal === null ? undefined : "run-from-refusal"}
            onKeep={(from) => onChange({ ...draft, from })}
          />
        </Choice>
        <Choice id="run-to" label="To" refusal={toRefusal}>
          <KeptField
            id="run-to"
            value={dates.to}
            invalid={toRefusal !== null}
            describedBy={toRefusal === null ? undefined : "run-to-refusal"}
            onKeep={(to) => onChange({ ...draft, to })}
          />
        </Choice>
        <Button
          variant="ghost"
          className="mt-6"
          data-testid="run-whole-range"
          onClick={() => onChange({ ...draft, from: null, to: null })}
        >
          Whole range
        </Button>
      </div>
      <p data-testid="run-coverage" className="text-xs text-muted-foreground">
        {`${estimate.settings.provider} holds ${series} from ${held.start} to ${held.end}`}
      </p>
    </div>
  )
}
