import type { RunEstimated } from "@/api/runs"
import { fidelityLabel } from "@/ui/figures"
import { KeptField } from "@/ui/kept-field"
import { Choice, Picker } from "@/ui/picker"
import {
  feeTableOf,
  type RunDraft,
  shownTicks,
  ticksRefusal,
} from "./run-draft"

/** The fidelity select's first choice, the setting left out. No level is written so. */
const AUTO = "(auto)"

type RunCostFieldsProps = Readonly<{
  draft: RunDraft
  estimate: RunEstimated
  onChange: (draft: RunDraft) => void
}>

/** How the run fills and what it costs: the fidelity, Auto by default, each level the data
 * holds; the fee table, among those that price the instrument; and the ticks of slippage on
 * market and stop orders, each showing the run's default until it is typed, so that a change of
 * fidelity still moves it. */
export function RunCostFields({
  draft,
  estimate,
  onChange,
}: RunCostFieldsProps) {
  const feeTable = feeTableOf(draft, estimate)
  return (
    <>
      <div className="grid grid-cols-2 items-start gap-4">
        <div className="flex flex-col gap-2">
          <Choice id="run-fidelity" label="Fidelity">
            <Picker
              id="run-fidelity"
              className="w-full"
              value={draft.fidelity === null ? AUTO : draft.fidelity}
              options={[
                { value: AUTO, label: "Auto" },
                ...estimate.levels.map((level) => ({
                  value: level,
                  label: fidelityLabel(level),
                })),
              ]}
              onChange={(chosen) =>
                onChange({
                  ...draft,
                  fidelity: chosen === AUTO ? null : chosen,
                })
              }
            />
          </Choice>
          <p
            data-testid="run-fidelity-note"
            className="text-xs text-muted-foreground"
          >
            {draft.fidelity === null
              ? `Each date fills on the finest data it holds, down to ${levelInASentence(estimate.settings.fidelity)}`
              : "Each date fills on this level, or the next coarser it holds"}
          </p>
        </div>
        {estimate.fee_tables.length === 0 ? (
          <p
            role="alert"
            data-testid="run-no-fee-table"
            className="text-negative"
          >
            {`No fee table prices ${estimate.instrument}, so a run could not count its costs.`}
          </p>
        ) : (
          <Choice id="run-fee-table" label="Fee table">
            <Picker
              id="run-fee-table"
              className="w-full"
              value={feeTable === null ? "" : feeTable}
              placeholder="Choose a table"
              options={estimate.fee_tables.map((table) => ({
                value: table,
                label: table,
              }))}
              onChange={(chosen) => onChange({ ...draft, feeTable: chosen })}
            />
          </Choice>
        )}
      </div>
      <RunSlippage draft={draft} estimate={estimate} onChange={onChange} />
    </>
  )
}

/** A level as a sentence writes it: lower case, an acronym as it is. */
function levelInASentence(level: string): string {
  return level === "tbbo" ? "TBBO" : fidelityLabel(level).toLowerCase()
}

function RunSlippage({ draft, estimate, onChange }: RunCostFieldsProps) {
  const ticks = shownTicks(draft, estimate)
  const marketRefusal = ticksRefusal(ticks.market)
  const stopRefusal = ticksRefusal(ticks.stop)
  return (
    <div className="grid grid-cols-2 items-start gap-4">
      <Choice
        id="run-slippage-market"
        label="Slippage on market orders, ticks"
        refusal={marketRefusal}
      >
        <KeptField
          id="run-slippage-market"
          value={ticks.market}
          invalid={marketRefusal !== null}
          describedBy={
            marketRefusal === null ? undefined : "run-slippage-market-refusal"
          }
          onKeep={(market) =>
            onChange({ ...draft, slippage: { ...draft.slippage, market } })
          }
        />
      </Choice>
      <Choice
        id="run-slippage-stop"
        label="Slippage on stop orders, ticks"
        refusal={stopRefusal}
      >
        <KeptField
          id="run-slippage-stop"
          value={ticks.stop}
          invalid={stopRefusal !== null}
          describedBy={
            stopRefusal === null ? undefined : "run-slippage-stop-refusal"
          }
          onKeep={(stop) =>
            onChange({ ...draft, slippage: { ...draft.slippage, stop } })
          }
        />
      </Choice>
    </div>
  )
}
