import type { components } from "@/api/schema"
import type { ImportProfile, UploadedFile } from "@/api/imports"
import type { Role } from "./import-roles"
import type { PresetChoice } from "./import-search"

/** What the wizard reads: a trader's own file through a profile, or a Databento batch
 * download, which the Databento importer reads by its folder's path. */
export type Reading = "file" | "batch"

/** One or several files chosen and copied into FEAT's folder. */
export type ChosenUploads = readonly [UploadedFile, ...UploadedFile[]]

/** The files the wizard reads: none yet, one or several chosen and copied into FEAT's folder,
 * several imported in one round (D-102), or one named by its path under the import roots. */
export type Source =
  | Readonly<{ kind: "none" }>
  | Readonly<{ kind: "uploads"; uploads: ChosenUploads }>
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

/** A kind of problem of a round that a correction fits, asked once for every file of the kind
 * (D-106): bars in a break, or records that differ. */
export type Correctable = "bars in breaks" | "differing"

/** The answer for every file of a kind: the correction, or a skip. */
export type Answer = "corrected" | "skipped"

/** The wizard's draft: everything the trader chose and typed, from which each preview and the
 * import are asked; the files whose records that differ from the stored ones are taken in their
 * place (ADR-0021) and those whose bars in a break are left out (ADR-0022), each as the trader
 * chose it for that file, by its upload's id or its path; and the files of a round the trader
 * skipped, which the round never sends (D-105). */
export type Draft = Readonly<{
  reading: Reading
  source: Source
  profile: ProfileDraft
  timeZone: string
  contract: string
  root: string
  instrument: InstrumentDraft
  recordsTaken: readonly string[]
  breaksLeftOut: readonly string[]
  skipped: readonly string[]
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
  | Readonly<{ kind: "records taken"; files: readonly string[] }>
  | Readonly<{ kind: "bars in breaks"; files: readonly string[] }>
  | Readonly<{ kind: "skipped"; files: readonly string[] }>
  | Readonly<{
      kind: "decided"
      problem: Correctable
      files: readonly string[]
      answer: Answer
    }>

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
    recordsTaken: [],
    breaksLeftOut: [],
    skipped: [],
  }
}

/** The draft after `change`. A change of what is read takes no file's records any more, leaves
 * no file's bars in a break out, and skips no file, since the trader chose each for the reading
 * the review showed (ADR-0021, ADR-0022, D-105); leaving out a file's bars, or putting them back,
 * reads that file again, so its records are taken no more, the other files' staying taken
 * (`withBarsLeftOut`); taking records and skipping keep the other decisions; and a round's box
 * decides for every file of its kind at once (`decidedFor`, D-106). */
export function drafted(draft: Draft, change: DraftChange): Draft {
  const refused = {
    ...draft,
    recordsTaken: [],
    breaksLeftOut: [],
    skipped: [],
  } satisfies Draft
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
    case "records taken":
      return { ...draft, recordsTaken: change.files }
    case "bars in breaks":
      return withBarsLeftOut(draft, change.files)
    case "skipped":
      return { ...draft, skipped: change.files }
    case "decided":
      return decidedFor(draft, change)
  }
}

/** The draft once a round's box is answered for every file of its kind, `files` (D-106). The
 * correction goes to those not skipped, so that a skip made in a row stands, or where each is
 * skipped, to them all, skipped no more: their bars left out, or their records taken. A skip
 * skips them all and takes the correction back from each, its bars in again or its records
 * refused, so that Do not skip in a row never brings back a correction unseen. */
function decidedFor(
  draft: Draft,
  { problem, files, answer }: Extract<DraftChange, { kind: "decided" }>
): Draft {
  if (answer === "skipped") {
    const skipped = [...without(draft.skipped, files), ...files]
    return problem === "differing"
      ? { ...draft, skipped, recordsTaken: without(draft.recordsTaken, files) }
      : withBarsLeftOut(
          { ...draft, skipped },
          without(draft.breaksLeftOut, files)
        )
  }
  const kept = without(files, draft.skipped)
  const chosen = kept.length > 0 ? kept : files
  const skipped = without(draft.skipped, chosen)
  return problem === "differing"
    ? {
        ...draft,
        skipped,
        recordsTaken: [...without(draft.recordsTaken, chosen), ...chosen],
      }
    : withBarsLeftOut({ ...draft, skipped }, [
        ...without(draft.breaksLeftOut, chosen),
        ...chosen,
      ])
}

/** The draft with the bars in a break of the files `breaksLeftOut` left out: a file whose bars go
 * out or come back in is read again, so its records are taken no more, since the trader chose to
 * take them for the reading the review showed (ADR-0022). */
function withBarsLeftOut(
  draft: Draft,
  breaksLeftOut: readonly string[]
): Draft {
  const changed = (file: string) =>
    breaksLeftOut.includes(file) !== draft.breaksLeftOut.includes(file)
  return {
    ...draft,
    breaksLeftOut,
    recordsTaken: draft.recordsTaken.filter((file) => !changed(file)),
  }
}

function without(
  files: readonly string[],
  gone: readonly string[]
): readonly string[] {
  return files.filter((file) => !gone.includes(file))
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
