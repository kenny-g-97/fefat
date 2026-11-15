import type {
  ColumnMapping,
  GivenProfile,
  ImportProfile,
  NewInstrument,
  TablePreview,
} from "@/api/imports"
import type {
  Delimiter,
  InstrumentDraft,
  InstrumentFields,
  Missing,
  ProfileFields,
} from "./import-draft"
import {
  type ColumnKey,
  mappingOf,
  ROLE_LABELS,
  type Role,
  rolesOf,
} from "./import-roles"

/** What a delimiter is called in a profile's description and the layout's select. */
export const DELIMITER_LABELS: Readonly<Record<Delimiter, string>> = {
  ",": "Commas",
  ";": "Semicolons",
  "\t": "Tabs",
  "|": "Bars",
}

/** A new profile, or what it still lacks. */
export type BuiltProfile =
  | Readonly<{ kind: "built"; profile: GivenProfile }>
  | Readonly<{ kind: "missing"; missing: readonly Missing[] }>

/** The profile the wizard's fields make of `base`: what the fields set over what the profile
 * they were copied from holds (plan call 10), its columns those the table's selects chose or
 * the base's, its description written from the fields, and the new instrument where there is
 * one. */
export function profileOf(
  base: ImportProfile,
  fields: ProfileFields,
  instrument: InstrumentDraft,
  table: TablePreview | null
): BuiltProfile {
  const columns = columnsOf(base, fields, table)
  const made = newInstrumentOf(instrument)
  const missing: readonly Missing[] = [
    ...blank(fields.name, "layout", "Give the profile a name"),
    ...blank(fields.provider, "layout", "Name the provider"),
    ...blank(fields.format, "layout", "Give the timestamp's format"),
    ...(columns.kind === "missing" ? columns.missing : []),
    ...(made.kind === "missing" ? made.missing : []),
  ]
  if (
    missing.length > 0 ||
    columns.kind === "missing" ||
    made.kind === "missing"
  ) {
    return { kind: "missing", missing }
  }
  return {
    kind: "built",
    profile: {
      ...base,
      name: fields.name.trim(),
      provider: fields.provider.trim(),
      description: described(fields),
      layout: { delimiter: fields.delimiter, header: fields.header },
      columns: columns.mapping,
      timestamp: {
        format: fields.format.trim(),
        time_zone:
          fields.timeZone.trim() === "" ? null : fields.timeZone.trim(),
        stamp: fields.stamp,
      },
      timeframe: fields.timeframe,
      instrument: made.kind === "new" ? made.instrument : base.instrument,
    },
  }
}

/** A new profile's description, from what its fields set, as the presets' read. */
export function described(fields: ProfileFields): string {
  const header = fields.header ? "a header row" : "no header"
  const zone =
    fields.timeZone.trim() === ""
      ? "the import's time zone"
      : fields.timeZone.trim()
  const timeframe =
    fields.timeframe === "ticks" ? "ticks" : `${fields.timeframe} bars`
  const delimiter = DELIMITER_LABELS[fields.delimiter].toLowerCase()
  return `${fields.provider.trim()} ${timeframe}: ${delimiter}, ${header}, ${zone}, stamped at the ${fields.stamp}`
}

/** The keys of a table's columns as a profile names them: their header's names, or their
 * places from 0 in a file without a header row. */
export function columnKeys(
  table: TablePreview,
  header: boolean
): readonly ColumnKey[] {
  return header ? table.columns : table.columns.map((_, index) => index)
}

/** The roles the table's selects show: those chosen, else what the base's columns give the
 * table's. */
export function shownRoles(
  base: ImportProfile,
  fields: ProfileFields,
  table: TablePreview
): readonly Role[] {
  if (fields.roles.kind === "chosen") {
    return fields.roles.roles
  }
  return rolesOf(base.columns, columnKeys(table, fields.header))
}

type Columns =
  | Readonly<{ kind: "mapped"; mapping: ColumnMapping }>
  | Readonly<{ kind: "missing"; missing: readonly Missing[] }>

function columnsOf(
  base: ImportProfile,
  fields: ProfileFields,
  table: TablePreview | null
): Columns {
  if (fields.roles.kind === "kept") {
    return { kind: "mapped", mapping: base.columns }
  }
  if (table === null) {
    return {
      kind: "missing",
      missing: [
        {
          card: "layout",
          text: "Wait for the file's table, to map its columns",
        },
      ],
    }
  }
  const keys = columnKeys(table, fields.header)
  const ticks = fields.timeframe === "ticks"
  const mapped = mappingOf(fields.roles.roles, keys, ticks, base.columns)
  if (mapped.kind === "missing") {
    return {
      kind: "missing",
      missing: mapped.roles.map((role) => ({
        card: "layout",
        text: `Choose the column of the ${ROLE_LABELS[role].toLowerCase()}`,
      })),
    }
  }
  return { kind: "mapped", mapping: mapped.mapping }
}

type Made =
  | Readonly<{ kind: "profile's" }>
  | Readonly<{ kind: "new"; instrument: NewInstrument }>
  | Readonly<{ kind: "missing"; missing: readonly Missing[] }>

function newInstrumentOf(instrument: InstrumentDraft): Made {
  if (instrument.kind === "profile's") {
    return instrument
  }
  const fields = instrument.fields
  const missing: readonly Missing[] = [
    ...blank(fields.root, "instrument", "Give the instrument's root"),
    ...blank(fields.tickSize, "instrument", "Give its tick size"),
    ...blank(fields.pointValue, "instrument", "Give its point value"),
    ...blank(fields.firstTradeDate, "instrument", "Give its first trade date"),
  ]
  if (missing.length > 0) {
    return { kind: "missing", missing }
  }
  return {
    kind: "new",
    instrument: {
      root: fields.root.trim(),
      kind: fields.kind,
      tick_size: fields.tickSize.trim(),
      point_value: fields.pointValue.trim(),
      lot_step: fields.lotStep.trim(),
      currency: fields.currency,
      calendar: fields.calendar,
      last_trade_rule: lastTradeRuleOf(fields),
      first_trade_date: fields.firstTradeDate,
    },
  }
}

function lastTradeRuleOf(
  fields: InstrumentFields
): NewInstrument["last_trade_rule"] {
  switch (fields.lastTradeRule) {
    case "none":
      return null
    case "third-friday":
      return { kind: "third-friday" }
    case "third-last-business-day":
      return { kind: "third-last-business-day" }
    case "business-days-before-the-25th":
      return {
        kind: "business-days-before-the-25th",
        business_days: Number(fields.businessDays),
      }
  }
}

function blank(
  text: string,
  card: Missing["card"],
  said: string
): readonly Missing[] {
  return text.trim() === "" ? [{ card, text: said }] : []
}
