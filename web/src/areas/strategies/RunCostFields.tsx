import type { Currency, Fee, RunEstimated } from "@/api/runs"
import { feeWords, fidelityLabel } from "@/ui/figures"
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
 * holds; the commissions and fees, the fee tables that price the instrument, each with what it
 * charges on the window's last day (D-117); and the ticks of slippage on market and stop orders,
 * each showing the run's default until it is typed, so that a change of fidelity still moves it. */
export function RunCostFields({
  draft,
  estimate,
  onChange,
}: RunCostFieldsProps) {
  const level = draft.fidelity === null ? AUTO : draft.fidelity
  const held = level === AUTO || estimate.levels.includes(level)
  return (
    <>
      <div className="grid grid-cols-2 items-start gap-4">
        <div className="flex flex-col gap-2">
          <Choice id="run-fidelity" label="Fidelity">
            <Picker
              id="run-fidelity"
              className="w-full"
              value={held ? level : ""}
              placeholder="Choose a level"
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
            {!held
              ? "The data does not hold the level chosen"
              : draft.fidelity === null
                ? `Each date fills on the finest data it holds, down to ${levelInASentence(estimate.settings.fidelity)}`
                : "Each date fills on this level, or the next coarser it holds"}
          </p>
        </div>
        <RunFees draft={draft} estimate={estimate} onChange={onChange} />
      </div>
      <RunSlippage draft={draft} estimate={estimate} onChange={onChange} />
    </>
  )
}

/** The commissions and fees: the fee tables that price the instrument, each named in the list
 * with its charge, the trigger naming the table, and a line under it saying what the charge holds;
 * where none prices the instrument, why a run cannot count its costs. */
function RunFees({ draft, estimate, onChange }: RunCostFieldsProps) {
  const feeTable = feeTableOf(draft, estimate)
  const chosen = estimate.fee_tables.find((choice) => choice.name === feeTable)
  if (estimate.fee_tables.length === 0) {
    return (
      <p role="alert" data-testid="run-no-fee-table" className="text-negative">
        {`No table of commissions and fees prices ${estimate.instrument}, so a run could not count its costs.`}
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <Choice id="run-fee-table" label="Commissions and fees">
        <Picker
          id="run-fee-table"
          className="w-full"
          value={feeTable === null ? "" : feeTable}
          shown={feeTable === null ? undefined : feeTable}
          placeholder="Choose a table"
          options={estimate.fee_tables.map((choice) => ({
            value: choice.name,
            label: `${choice.name}, ${feeWords(choice.fee, estimate.currency)}`,
          }))}
          onChange={(name) => onChange({ ...draft, feeTable: name })}
        />
      </Choice>
      {chosen !== undefined && (
        <p data-testid="run-fee-note" className="text-xs text-muted-foreground">
          {feeNote(chosen.fee, estimate.currency)}
        </p>
      )}
    </div>
  )
}

/** What a table's charge holds, as the line under the field says it. */
function feeNote(fee: Fee, currency: Currency): string {
  const charge = feeWords(fee, currency)
  return fee.kind === "futures"
    ? `${charge}: the exchange's, clearing, and NFA fees with the broker's commission`
    : `${charge} of each trade's value, maker for a limit order that rested on the book`
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
