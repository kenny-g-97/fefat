import { Palette } from "lucide-react"
import { type FormEvent, useState } from "react"
import { timeframe } from "@/api/bar-windows"
import type { BarPrices } from "@/api/bars"
import { Button } from "@/ui/button"
import { Input } from "@/ui/input"
import { Label } from "@/ui/label"
import { Segmented } from "@/ui/segmented"
import { SheetTrigger } from "@/ui/sheet"
import { contractChoice } from "./chart-panes"
import type { ChartSearch } from "./chart-search"
import { Choice, type Option, Picker } from "./Picker"

type ChartToolbarProps = Readonly<{
  roots: readonly string[]
  root: string
  futures: boolean
  providers: readonly string[]
  shown: ChartSearch
  onChoose: (change: Partial<ChartSearch>) => void
}>

const PRICES: readonly Readonly<{ value: BarPrices; label: string }>[] = [
  { value: "adjusted", label: "Adjusted" },
  { value: "raw", label: "Raw" },
]

/** The provider choice that leaves the provider out, for the catalog's recommended source: no
 * provider's folder name holds parentheses (`fefat.market.layout.FolderName`). */
const RECOMMENDED = "(recommended)"

function named(values: readonly string[]): readonly Option[] {
  return values.map((value) => ({ value, label: value }))
}

/** The chart's choices (web/DESIGN.md, Patterns, Price chart): the instrument, a contract of it
 * to chart alone, the provider where several hold it, the timeframe, adjusted or raw prices for
 * a futures root's spliced series, and the chart's style. */
export function ChartToolbar({
  roots,
  root,
  futures,
  providers,
  shown,
  onChoose,
}: ChartToolbarProps) {
  return (
    <div className="flex shrink-0 flex-wrap items-end gap-4">
      <Choice id="chart-instrument" label="Instrument">
        <Picker
          id="chart-instrument"
          value={root}
          options={named(roots)}
          onChange={(value) =>
            onChoose({
              instrument: value,
              contract: undefined,
              provider: undefined,
            })
          }
        />
      </Choice>
      {futures && (
        <ContractField
          key={`${root} ${shown.contract}`}
          root={root}
          contract={shown.contract}
          onChoose={onChoose}
        />
      )}
      {providers.length > 1 && (
        <Choice id="chart-provider" label="Provider">
          <Picker
            id="chart-provider"
            value={shown.provider === undefined ? RECOMMENDED : shown.provider}
            options={[
              { value: RECOMMENDED, label: "Recommended" },
              ...named(providers),
            ]}
            onChange={(value) =>
              onChoose({ provider: value === RECOMMENDED ? undefined : value })
            }
          />
        </Choice>
      )}
      <Choice id="chart-timeframe" label="Timeframe">
        <Picker
          id="chart-timeframe"
          value={shown.timeframe}
          options={named(timeframe.options)}
          onChange={(value) => onChoose({ timeframe: timeframe.parse(value) })}
        />
      </Choice>
      {futures && shown.contract === undefined && (
        <Segmented
          label="Prices"
          options={PRICES}
          value={shown.prices}
          onChange={(prices) => onChoose({ prices })}
        />
      )}
      <SheetTrigger asChild>
        <Button data-slot="button" variant="ghost" className="ml-auto">
          <Palette className="size-4" />
          Chart style
        </Button>
      </SheetTrigger>
    </div>
  )
}

type ContractFieldProps = Readonly<{
  root: string
  contract: string | undefined
  onChoose: (change: Partial<ChartSearch>) => void
}>

/** A contract of the root to chart alone, kept with Enter or once the field is left, as a field's
 * rules are checked (web/DESIGN.md, Forms); nothing charts the root's spliced series. */
function ContractField({ root, contract, onChoose }: ContractFieldProps) {
  const [typed, setTyped] = useState(contract === undefined ? "" : contract)
  const [refusal, setRefusal] = useState<string | null>(null)
  const keep = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const chosen = contractChoice(root, typed, new Date().getFullYear())
    if (chosen.kind === "refused") {
      setRefusal(chosen.message)
      return
    }
    setRefusal(null)
    onChoose({
      contract: chosen.kind === "contract" ? chosen.contract : undefined,
    })
  }
  return (
    <form onSubmit={keep} noValidate className="relative flex flex-col gap-2">
      <Label htmlFor="chart-contract">Contract</Label>
      <Input
        id="chart-contract"
        value={typed}
        placeholder="Spliced"
        autoComplete="off"
        aria-invalid={refusal !== null}
        className="w-40"
        onChange={(event) => setTyped(event.target.value.toUpperCase())}
        onBlur={(event) => {
          if (typed !== (contract === undefined ? "" : contract)) {
            event.currentTarget.form?.requestSubmit()
          }
        }}
      />
      {refusal !== null && (
        <p
          role="alert"
          className="absolute top-full pt-1 text-xs whitespace-nowrap text-negative"
        >
          {refusal}
        </p>
      )}
    </form>
  )
}
