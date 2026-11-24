import { cn } from "cn"
import type { ReactNode } from "react"
import type { Currency, Fee, ListedRun } from "@/api/runs"
import { counted, fidelityLabel, formatMoney } from "@/ui/figures"
import { IdentityChip } from "@/ui/identity-chip"
import { Panel } from "@/ui/panel"
import { parameterText } from "./run-words"

/** A label and its value. */
type Fact = readonly [string, ReactNode]

/** A list of labels and values (web/DESIGN.md, Patterns, Run page), each label in body text and
 * its value in heading text, aligned right where the values are `figures`. */
function Facts({
  facts,
  figures = false,
}: Readonly<{
  facts: readonly Fact[]
  figures?: boolean
}>) {
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] content-start gap-x-6 gap-y-2">
      {facts.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-foreground-secondary">{label}</dt>
          <dd
            className={cn(
              "wrap-anywhere text-foreground",
              figures && "text-right"
            )}
          >
            {value}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** The parameters a run ran with, every default applied once it is saved. */
export function RunParametersCard({ run }: Readonly<{ run: ListedRun }>) {
  const parameters = Object.entries(run.parameters)
  return (
    <Panel title="Parameters">
      {parameters.length === 0 ? (
        <p className="text-foreground-secondary">
          {run.strategy === null
            ? "A strategy built in a notebook names none."
            : "It takes no parameters."}
        </p>
      ) : (
        <Facts
          figures
          facts={parameters.map(([name, value]) => [
            name,
            parameterText(value),
          ])}
        />
      )}
    </Panel>
  )
}

/** What a fee table charges, as a row of the Settings card: per contract per side, or a crypto
 * fee's maker and taker rates. */
function chargeFact(fee: Fee, currency: Currency | null): Fact {
  return fee.kind === "futures"
    ? ["Per contract per side", formatMoney(fee.per_contract_side, currency)]
    : ["Maker, taker", `${fee.maker_bps} bps, ${fee.taker_bps} bps`]
}

/** Every setting a run runs under, each default applied, as its record keeps them: its capital in
 * its currency, and its costs together, the fee table with what it charges the instrument on the
 * run's last day beside the slippage, where its row names the instrument (D-117). */
export function RunSettingsCard({ run }: Readonly<{ run: ListedRun }>) {
  const { settings, currency, fee } = run
  const instrument = settings.instrument ?? null
  const traded: readonly Fact[] =
    instrument === null ? [] : [["Instrument", instrument]]
  const left: readonly Fact[] = [
    ...traded,
    ["Data", <IdentityChip key="provider">{settings.provider}</IdentityChip>],
    ["Contract", settings.contract === null ? "Spliced" : settings.contract],
    ["Fidelity", fidelityLabel(settings.fidelity)],
    ["Capital", formatMoney(settings.capital, currency)],
  ]
  const charged: readonly Fact[] =
    fee === null ? [] : [chargeFact(fee, currency)]
  const right: readonly Fact[] = [
    ["Commissions and fees", settings.fee_table],
    ...charged,
    [
      "Slippage on market orders",
      counted(settings.slippage_ticks.market, "tick"),
    ],
    ["Slippage on stop orders", counted(settings.slippage_ticks.stop, "tick")],
    ["Latency", `${settings.latency_ms} ms`],
    [
      "Limit orders fill",
      settings.limit_fill === "through" ? "Through" : "On touch",
    ],
    [
      "A roll",
      settings.roll_handling === "transfer" ? "Transfers" : "Flattens",
    ],
  ]
  return (
    <Panel title="Settings">
      <div
        data-testid="run-settings"
        className="grid grid-cols-[auto_auto] gap-x-12"
      >
        <Facts facts={left} />
        <Facts facts={right} />
      </div>
    </Panel>
  )
}
