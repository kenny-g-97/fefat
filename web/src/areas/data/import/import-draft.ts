import type { components } from "@/api/schema"
import type { ImportProfile, UploadedFile } from "@/api/imports"
import type { Role } from "./import-roles"
import type { PresetChoice } from "./import-search"

/** What the wizard reads: a trader's own file through a profile, or a Databento batch
 * download, which the Databento importer reads by its folder's path. */
export type Reading = "file" | "batch"

/** The file the wizard reads: none yet, one chosen and copied into FEAT's folder, or one
 * named by its path under the import roots. */
export type Source =
  | Readonly<{ kind: "none" }>
  | Readonly<{ kind: "upload"; upload: UploadedFile }>
  | Readonly<{ kind: "path"; path: string }>

/** A file's field delimiter, one character, as a profile's layout holds it. */
export type Delimiter = string

/** A profile's columns: those of the profile it was copied from, until a select over the
 * file's table chooses them, a role a column. */
export type ColumnRoles =
  | Readonly<{ kind: "kept" }>
  | Readonly<{ kind: "chosen"; roles: readonly Role[] }>

/** What the wizard's new profile sets; the rest is the profile it was copied from (plan call
 * 10). */
export type ProfileFields = Readonly<{
  name: string
  provider: string
  delimiter: Delimiter
  header: boolean
  format: string
  timeZone: string
  stamp: components["schemas"]["BarStamp"]
  timeframe: string
  roles: ColumnRoles
}>

/** The profile the file is read with: none chosen yet, a preset or a saved profile by its
 * name, or a new one copied from `base`. */
export type ProfileDraft =
  | Readonly<{ kind: "none" }>
  | Readonly<{ kind: "listed"; name: string }>
  | Readonly<{ kind: "new"; base: string; fields: ProfileFields }>

export type LastTradeRuleKind =
  | "third-friday"
  | "third-last-business-day"
  | "business-days-before-the-25th"
  | "none"

/** A new instrument's specification, as the wizard's fields hold it, decimals as typed. */
export type InstrumentFields = Readonly<{
  root: string
  kind: components["schemas"]["InstrumentKind"]
  tickSize: string
  pointValue: string
  lotStep: string
  currency: components["schemas"]["Currency"]
  calendar: components["schemas"]["CalendarId"]
  lastTradeRule: LastTradeRuleKind
  businessDays: string
  firstTradeDate: string
}>

/** The instrument the records are of: the one the profile and the file name, or a new one,
 * which a new profile carries. */
export type InstrumentDraft =
  | Readonly<{ kind: "profile's" }>
  | Readonly<{ kind: "new"; fields: InstrumentFields }>

export type DifferingRecords = components["schemas"]["DifferingRecords"]

/** The wizard's draft: everything the trader chose and typed, from which each preview and the
 * import are asked. */
export type Draft = Readonly<{
  reading: Reading
  source: Source
  profile: ProfileDraft
  timeZone: string
  contract: string
  root: string
  instrument: InstrumentDraft
  differing: DifferingRecords
}>

export type DraftChange =
  | Readonly<{ kind: "reading"; reading: Reading }>
  | Readonly<{ kind: "source"; source: Source }>
  | Readonly<{ kind: "listed profile"; name: string }>
  | Readonly<{ kind: "new profile"; base: ImportProfile }>
  | Readonly<{ kind: "profile fields"; fields: Partial<ProfileFields> }>
  | Readonly<{ kind: "time zone"; timeZone: string }>
  | Readonly<{ kind: "contract"; contract: string }>
  | Readonly<{ kind: "root"; root: string }>
  | Readonly<{ kind: "instrument"; instrument: InstrumentDraft }>
  | Readonly<{ kind: "instrument fields"; fields: Partial<InstrumentFields> }>
  | Readonly<{ kind: "differing"; differing: DifferingRecords }>

/** A new instrument's fields before the trader types them: futures in US dollars on the CME's
 * equity index calendar, expiring on the third Friday, as the most common product is. */
export const NEW_INSTRUMENT: InstrumentFields = {
  root: "",
  kind: "futures",
  tickSize: "",
  pointValue: "",
  lotStep: "1",
  currency: "USD",
  calendar: "cme-equity-index",
  lastTradeRule: "third-friday",
  businessDays: "3",
  firstTradeDate: "",
}

/** The draft a preset in the address starts from (`presetChoice`). */
export function startingDraft(choice: PresetChoice): Draft {
  return {
    reading: choice.kind === "batch" ? "batch" : "file",
    source: { kind: "none" },
    profile:
      choice.kind === "profile"
        ? { kind: "listed", name: choice.name }
        : { kind: "none" },
    timeZone: "",
    contract: "",
    root: "",
    instrument: { kind: "profile's" },
    differing: "refuse",
  }
}

/** The draft after `change`: any change but the choice of what to do with differing records
 * refuses them again, since the trader chose to take them for the file the review showed. */
export function drafted(draft: Draft, change: DraftChange): Draft {
  const refused = { ...draft, differing: "refuse" } satisfies Draft
  switch (change.kind) {
    case "reading":
      return { ...refused, reading: change.reading, source: { kind: "none" } }
    case "source":
      return { ...refused, source: change.source }
    case "listed profile":
      return {
        ...refused,
        profile: { kind: "listed", name: change.name },
        instrument: { kind: "profile's" },
      }
    case "new profile":
      return {
        ...refused,
        profile: {
          kind: "new",
          base: change.base.name,
          fields: fieldsOf(change.base, draft.timeZone),
        },
      }
    case "profile fields":
      return {
        ...refused,
        profile: editedProfile(draft.profile, change.fields),
      }
    case "time zone":
      return { ...refused, timeZone: change.timeZone }
    case "contract":
      return { ...refused, contract: change.contract }
    case "root":
      return { ...refused, root: change.root }
    case "instrument":
      return { ...refused, instrument: change.instrument }
    case "instrument fields":
      return {
        ...refused,
        instrument: editedInstrument(draft.instrument, change.fields),
      }
    case "differing":
      return { ...draft, differing: change.differing }
  }
}

/** A new profile's fields, from the profile it is copied from, under a name of the trader's
 * own; where that profile leaves the time zone to the import, the one typed for it, since a new
 * profile names its own. */
export function fieldsOf(
  base: ImportProfile,
  typedZone: string
): ProfileFields {
  return {
    name: `my-${base.name}`,
    provider: base.provider,
    delimiter: base.layout.delimiter,
    header: base.layout.header,
    format: base.timestamp.format,
    timeZone:
      base.timestamp.time_zone === null ? typedZone : base.timestamp.time_zone,
    stamp: base.timestamp.stamp,
    timeframe: base.timeframe,
    roles: { kind: "kept" },
  }
}

function editedProfile(
  profile: ProfileDraft,
  fields: Partial<ProfileFields>
): ProfileDraft {
  if (profile.kind !== "new") {
    throw new Error(
      `Expected a new profile to edit, got a ${profile.kind} one.`
    )
  }
  return { ...profile, fields: { ...profile.fields, ...fields } }
}

function editedInstrument(
  instrument: InstrumentDraft,
  fields: Partial<InstrumentFields>
): InstrumentDraft {
  if (instrument.kind !== "new") {
    throw new Error("Expected a new instrument to edit, got the profile's.")
  }
  return { kind: "new", fields: { ...instrument.fields, ...fields } }
}

/** Which card of the wizard holds a field. */
export type Card = "file" | "layout" | "instrument"

/** Something the review waits for, in the words of the field to fill, under the card that
 * holds it. */
export type Missing = Readonly<{ card: Card; text: string }>
