import type { Dispatch } from "react"
import { KeptField } from "@/ui/kept-field"
import { Choice, Picker } from "../Picker"
import {
  delimiterOf,
  type DraftChange,
  type ProfileFields,
} from "./import-draft"
import { DELIMITER_LABELS, described } from "./import-profile"
import { type Choice as Option, RadioChoice } from "./RadioChoice"

const DELIMITERS = Object.entries(DELIMITER_LABELS).map(([value, label]) => ({
  value,
  label,
}))

/** The timeframes a profile reads: ticks, or bars of a second to a day; the chart's list has no
 * second and no ticks, so the wizard keeps its own. */
const TIMEFRAMES = [
  "ticks",
  "1s",
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "4h",
  "1d",
].map((value) => ({
  value,
  label: value === "ticks" ? "Ticks" : value,
}))

const HEADERS: readonly Option<"header" | "none">[] = [
  { value: "header", label: "Names the columns" },
  { value: "none", label: "Holds a record" },
]

const STAMPS: readonly Option<ProfileFields["stamp"]>[] = [
  { value: "open", label: "At its open" },
  { value: "close", label: "At its close" },
]

type ProfileFormProps = Readonly<{
  fields: ProfileFields
  change: Dispatch<DraftChange>
}>

/** A new profile's fields (plan call 10): its name and provider, the file's delimiter and
 * header row, its timestamps' format, time zone, and side of the bar, and its timeframe, each
 * kept as it is chosen or its field left; its description is written from them. What a profile
 * holds besides stays the profile's it was made from, and is set in its YAML file. */
export function ProfileForm({ fields, change }: ProfileFormProps) {
  const set = (changed: Partial<ProfileFields>) =>
    change({ kind: "profile fields", fields: changed })
  return (
    <div className="flex flex-col gap-5" data-testid="profile-form">
      <div className="flex flex-wrap gap-4">
        <Choice id="profile-name" label="Name">
          <KeptField
            id="profile-name"
            value={fields.name}
            className="w-56"
            onKeep={(name) => set({ name })}
          />
        </Choice>
        <Choice id="profile-provider" label="Provider">
          <KeptField
            id="profile-provider"
            value={fields.provider}
            className="w-48"
            onKeep={(provider) => set({ provider })}
          />
        </Choice>
        <Choice id="profile-timeframe" label="Timeframe">
          <Picker
            id="profile-timeframe"
            value={fields.timeframe}
            options={TIMEFRAMES}
            onChange={(timeframe) =>
              set({ timeframe, roles: { kind: "kept" } })
            }
          />
        </Choice>
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <Choice id="profile-delimiter" label="Fields separated by">
          <Picker
            id="profile-delimiter"
            value={fields.delimiter}
            options={DELIMITERS}
            onChange={(delimiter) =>
              set({
                delimiter: delimiterOf(delimiter),
                roles: { kind: "kept" },
              })
            }
          />
        </Choice>
        <RadioChoice
          id="profile-header"
          label="First row"
          options={HEADERS}
          value={fields.header ? "header" : "none"}
          onChange={(header) =>
            set({ header: header === "header", roles: { kind: "kept" } })
          }
        />
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <Choice id="profile-format" label="Timestamp format">
          <KeptField
            id="profile-format"
            value={fields.format}
            placeholder="%Y-%m-%d %H:%M:%S"
            className="w-56"
            onKeep={(format) => set({ format })}
          />
        </Choice>
        <Choice id="profile-time-zone" label="Time zone">
          <KeptField
            id="profile-time-zone"
            value={fields.timeZone}
            placeholder="UTC"
            className="w-56"
            onKeep={(timeZone) => set({ timeZone })}
          />
        </Choice>
        <RadioChoice
          id="profile-stamp"
          label="A bar's timestamp"
          options={STAMPS}
          value={fields.stamp}
          onChange={(stamp) => set({ stamp })}
        />
      </div>
      <p
        className="text-xs text-muted-foreground"
        data-testid="profile-description"
      >
        {described(fields)}
      </p>
    </div>
  )
}
