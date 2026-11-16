import type { Dispatch } from "react"
import type { components } from "@/api/schema"
import { KeptField } from "@/ui/kept-field"
import { Choice, Picker } from "../Picker"
import { picked } from "./choices"
import type {
  DraftChange,
  InstrumentFields,
  LastTradeRuleKind,
} from "./import-draft"

type Schemas = components["schemas"]

const KINDS = [
  { value: "futures", label: "Futures" },
  { value: "perpetual", label: "Perpetual" },
  { value: "spot", label: "Spot" },
] satisfies readonly { value: Schemas["InstrumentKind"]; label: string }[]

const CURRENCY_CODES: readonly Schemas["Currency"][] = [
  "USD",
  "USDT",
  "EUR",
  "GBP",
  "JPY",
  "CHF",
  "AUD",
  "CAD",
]

const CURRENCIES = CURRENCY_CODES.map((value) => ({ value, label: value }))

const CALENDARS = [
  { value: "cme-equity-index", label: "CME equity index" },
  { value: "cme-energy", label: "CME energy" },
  { value: "cme-metals", label: "CME metals" },
  { value: "crypto-24x7", label: "Crypto, every hour" },
] satisfies readonly { value: Schemas["CalendarId"]; label: string }[]

const LAST_TRADE_RULES = [
  { value: "third-friday", label: "Third Friday" },
  { value: "third-last-business-day", label: "Third last business day" },
  {
    value: "business-days-before-the-25th",
    label: "Business days before the 25th",
  },
  { value: "none", label: "None" },
] satisfies readonly { value: LastTradeRuleKind; label: string }[]

type InstrumentFormProps = Readonly<{
  fields: InstrumentFields
  change: Dispatch<DraftChange>
}>

/** A new instrument's specification, as a profile's YAML file holds one: its root, kind, tick
 * size, point value, lot step, and currency, its calendar among FEAT's, its contracts' last
 * trade rule, and its first trade date; decimals as typed, which the server reads exactly. A
 * calendar of hours of its own stays the YAML file's (plan call 10). */
export function InstrumentForm({ fields, change }: InstrumentFormProps) {
  const set = (changed: Partial<InstrumentFields>) =>
    change({ kind: "instrument fields", fields: changed })
  return (
    <div className="flex flex-col gap-5" data-testid="instrument-form">
      <div className="flex flex-wrap gap-5">
        <Text
          id="instrument-root"
          label="Root"
          value={fields.root}
          onKeep={(root) => set({ root: root.toUpperCase() })}
        />
        <Choice id="instrument-kind" label="Kind">
          <Picker
            id="instrument-kind"
            value={fields.kind}
            options={KINDS}
            onChange={(kind) => set({ kind: picked(KINDS, kind) })}
          />
        </Choice>
        <Choice id="instrument-currency" label="Currency">
          <Picker
            id="instrument-currency"
            value={fields.currency}
            options={CURRENCIES}
            onChange={(currency) =>
              set({ currency: picked(CURRENCIES, currency) })
            }
          />
        </Choice>
        <Choice id="instrument-calendar" label="Calendar">
          <Picker
            id="instrument-calendar"
            value={fields.calendar}
            options={CALENDARS}
            className="w-56"
            onChange={(calendar) =>
              set({ calendar: picked(CALENDARS, calendar) })
            }
          />
        </Choice>
      </div>
      <div className="flex flex-wrap gap-5">
        <Text
          id="instrument-tick"
          label="Tick size"
          value={fields.tickSize}
          placeholder="0.25"
          onKeep={(tickSize) => set({ tickSize })}
        />
        <Text
          id="instrument-point"
          label="Point value"
          value={fields.pointValue}
          placeholder="50"
          onKeep={(pointValue) => set({ pointValue })}
        />
        <Text
          id="instrument-lot"
          label="Lot step"
          value={fields.lotStep}
          onKeep={(lotStep) => set({ lotStep })}
        />
      </div>
      <div className="flex flex-wrap gap-5">
        <Choice id="instrument-last-trade" label="Last trade">
          <Picker
            id="instrument-last-trade"
            value={fields.lastTradeRule}
            options={LAST_TRADE_RULES}
            className="w-64"
            onChange={(rule) =>
              set({ lastTradeRule: picked(LAST_TRADE_RULES, rule) })
            }
          />
        </Choice>
        {fields.lastTradeRule === "business-days-before-the-25th" && (
          <Text
            id="instrument-business-days"
            label="Business days"
            value={fields.businessDays}
            onKeep={(businessDays) => set({ businessDays })}
          />
        )}
        <Text
          id="instrument-first-trade-date"
          label="First trade date"
          value={fields.firstTradeDate}
          placeholder="2010-09-27"
          onKeep={(firstTradeDate) => set({ firstTradeDate })}
        />
      </div>
    </div>
  )
}

type TextProps = Readonly<{
  id: string
  label: string
  value: string
  placeholder?: string
  onKeep: (value: string) => void
}>

function Text({ id, label, value, placeholder, onKeep }: TextProps) {
  return (
    <Choice id={id} label={label}>
      <KeptField
        id={id}
        value={value}
        placeholder={placeholder}
        className="w-36"
        onKeep={onKeep}
      />
    </Choice>
  )
}
