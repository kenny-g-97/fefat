import type { Dispatch } from "react"
import type { FileSeen } from "@/api/imports"
import { KeptField } from "@/ui/kept-field"
import { Choice, Picker } from "../Picker"
import type { DraftChange, ProfileFields } from "./import-draft"
import { DELIMITERS, delimiterName, described } from "./import-profile"
import { offsetRefusal } from "./import-request"
import { type Choice as Option, RadioChoice } from "@/ui/radio-choice"

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
  offsets: Readonly<FileSeen["offsets"]>
}>

/** A new profile's fields (plan call 10): its name and provider, the file's delimiter and
 * header row, its timestamps' format, time zone, and side of the bar, and its timeframe, each
 * kept as it is chosen or its field left; its description is written from them. The latest
 * review's offset stands under the field it points at, the time zone or the bar's timestamp
 * (Forms). What a profile holds besides stays the profile's it was made from, and is set in its
 * YAML file. */
export function ProfileForm({ fields, change, offsets }: ProfileFormProps) {
  const set = (changed: Partial<ProfileFields>) =>
    change({ kind: "profile fields", fields: changed })
  const zoneRefusal = offsetRefusal(offsets, "time zone")
  const delimiters = DELIMITERS.some((each) => each.value === fields.delimiter)
    ? DELIMITERS
    : [
        ...DELIMITERS,
        { value: fields.delimiter, label: delimiterName(fields.delimiter) },
      ]
  return (
    <div className="flex flex-col gap-5" data-testid="profile-form">
      <div className="flex flex-wrap items-start gap-5">
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
              set({
                timeframe,
                roles:
                  (timeframe === "ticks") === (fields.timeframe === "ticks")
                    ? fields.roles
                    : { kind: "kept" },
              })
            }
          />
        </Choice>
      </div>
      <div className="flex flex-wrap items-start gap-5">
        <Choice id="profile-delimiter" label="Fields separated by">
          <Picker
            id="profile-delimiter"
            value={fields.delimiter}
            options={delimiters}
            className="w-44"
            onChange={(delimiter) =>
              set({ delimiter, roles: { kind: "kept" } })
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
      <div className="flex flex-wrap items-start gap-5">
        <Choice id="profile-format" label="Timestamp format">
          <KeptField
            id="profile-format"
            value={fields.format}
            placeholder="%Y-%m-%d %H:%M:%S"
            className="w-56"
            onKeep={(format) => set({ format })}
          />
        </Choice>
        <Choice
          id="profile-time-zone"
          label="Time zone"
          refusal={zoneRefusal}
          className="w-56"
        >
          <KeptField
            id="profile-time-zone"
            value={fields.timeZone}
            placeholder="UTC"
            className="w-56"
            invalid={zoneRefusal !== null}
            describedBy={
              zoneRefusal === null ? undefined : "profile-time-zone-refusal"
            }
            onKeep={(timeZone) => set({ timeZone })}
          />
        </Choice>
        <RadioChoice
          id="profile-stamp"
          label="A bar's timestamp"
          options={STAMPS}
          value={fields.stamp}
          refusal={offsetRefusal(offsets, "bar stamp")}
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
