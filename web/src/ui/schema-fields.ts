import { z } from "zod"

/** A value a parameter takes: a number, a flag, or a word. */
export type ParameterValue = string | number | boolean

/** A parameter of a JSON schema the form draws, by its name as the code writes it: a number
 * typed as text, whole or not, a word typed as text, a flag, or one of a few values. */
export type ParameterField =
  | Readonly<{
      kind: "integer" | "number" | "string"
      name: string
      initial: string
      description: string | null
    }>
  | Readonly<{
      kind: "boolean"
      name: string
      initial: boolean
      description: string | null
    }>
  | Readonly<{
      kind: "choice"
      name: string
      options: readonly ParameterValue[]
      initial: ParameterValue
      description: string | null
    }>

/** Why the form cannot draw a schema, in words. */
type Unreadable = Readonly<{ kind: "unreadable"; reason: string }>

/** What a schema gives the form: its fields, or why it cannot draw them. */
export type SchemaReading =
  | Readonly<{ kind: "fields"; fields: readonly ParameterField[] }>
  | Unreadable

/** A typed text read as a parameter's value, or its refusal in words. */
export type TypedReading =
  | Readonly<{ kind: "valid"; value: ParameterValue }>
  | Readonly<{ kind: "refused"; message: string }>

const scalar = z.union([z.string(), z.number(), z.boolean()])

// shortcut: bounds, lengths, and patterns go unread and the server refuses them at a run, as
// no template declares one; read them here once a strategy, a feature, or a rule set does.
const property = z.object({
  type: z.enum(["integer", "number", "boolean", "string"]).optional(),
  enum: z.array(scalar).min(1).optional(),
  const: scalar.optional(),
  default: scalar,
  description: z.string().optional(),
})

const parameters = z.object({
  type: z.literal("object"),
  properties: z.record(z.string(), z.unknown()),
})

const WHOLE = /^[+-]?\d+$/
const DECIMAL = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/

/** The fields of `schema`, a version's parameters as Pydantic writes their JSON schema (step
 * 5.2): one for each property, in the order the code declares them, of a type, a `const`, or an
 * `enum`, with its default; else why the form cannot draw it. */
export function parameterFields(schema: unknown): SchemaReading {
  const read = parameters.safeParse(schema)
  if (!read.success) {
    return unreadable(
      "Expected the parameters as an object of named properties, got another shape."
    )
  }
  const fields: ParameterField[] = []
  for (const [name, given] of Object.entries(read.data.properties)) {
    const field = parameterField(name, given)
    if (field.kind === "unreadable") {
      return field
    }
    fields.push(field)
  }
  return { kind: "fields", fields }
}

/** What the trader entered in each field, by its name: a field's text, flag, or value chosen. */
export type EnteredValues = ReadonlyMap<string, ParameterValue>

/** Each field at its default, as the form first shows it. */
export function defaultEntries(
  fields: readonly ParameterField[]
): EnteredValues {
  return new Map(fields.map((field) => [field.name, field.initial]))
}

/** What `entered` holds for the field `name`. */
export function enteredValue(
  entered: EnteredValues,
  name: string
): ParameterValue {
  const value = entered.get(name)
  if (value === undefined) {
    throw new Error(`Expected a value entered for ${name}, got none.`)
  }
  return value
}

/** The parameters `entered` gives, each read as its field's type, as a run would take them; null
 * while a field holds a text its type refuses. */
export function parameterValues(
  fields: readonly ParameterField[],
  entered: EnteredValues
): Readonly<Record<string, ParameterValue>> | null {
  const values: Record<string, ParameterValue> = {}
  for (const field of fields) {
    const value = enteredValue(entered, field.name)
    if (field.kind === "boolean" || field.kind === "choice") {
      values[field.name] = value
      continue
    }
    const read = typedValue(field.kind, String(value), field.initial)
    if (read.kind === "refused") {
      return null
    }
    values[field.name] = read.value
  }
  return values
}

/** `typed` read as a value of a field of `kind`: a whole number, any number, or the text as it
 * is; refused with what to type, `example` being the field's default. */
export function typedValue(
  kind: "integer" | "number" | "string",
  typed: string,
  example: string
): TypedReading {
  if (kind === "string") {
    return { kind: "valid", value: typed }
  }
  const text = typed.trim()
  if (kind === "integer") {
    return WHOLE.test(text) && Number.isSafeInteger(Number(text))
      ? { kind: "valid", value: Number(text) }
      : { kind: "refused", message: `Type a whole number, such as ${example}.` }
  }
  return DECIMAL.test(text) && Number.isFinite(Number(text))
    ? { kind: "valid", value: Number(text) }
    : { kind: "refused", message: `Type a number, such as ${example}.` }
}

function parameterField(
  name: string,
  given: unknown
): ParameterField | Unreadable {
  const read = property.safeParse(given)
  if (!read.success) {
    return unreadable(
      `Expected ${name} with a default of a number, a flag, or a word, got another shape.`
    )
  }
  const { type, default: initial } = read.data
  const description = read.data.description ?? null
  const offered = offeredValues(read.data)
  if (offered !== null) {
    return offered.includes(initial)
      ? { kind: "choice", name, options: offered, initial, description }
      : unreadable(
          `Expected the default of ${name} among its values, got ${String(initial)}.`
        )
  }
  if (type === "boolean") {
    return typeof initial === "boolean"
      ? { kind: "boolean", name, initial, description }
      : unreadable(
          `Expected a flag as the default of ${name}, got ${String(initial)}.`
        )
  }
  if (type === undefined) {
    return unreadable(
      `Expected ${name} of a type the form draws, a number, a flag, a word, or one of a few values, got none.`
    )
  }
  const fits =
    type === "string"
      ? typeof initial === "string"
      : typeof initial === "number"
  return fits
    ? { kind: type, name, initial: shownDefault(type, initial), description }
    : unreadable(
        `Expected a default of type ${type} for ${name}, got ${String(initial)}.`
      )
}

/** A default as the code writes it: a float that is whole keeps its point, `30.0`, which JSON's
 * `30` hides, so that a float and a whole number never look alike. */
function shownDefault(
  type: "integer" | "number" | "string",
  initial: ParameterValue
): string {
  return type === "number" &&
    typeof initial === "number" &&
    Number.isInteger(initial)
    ? initial.toFixed(1)
    : String(initial)
}

/** The values a `Literal`'s property offers: its `enum`'s, or its one `const`'s; null for a
 * property of a type alone. */
function offeredValues(
  read: z.infer<typeof property>
): readonly ParameterValue[] | null {
  if (read.enum !== undefined) {
    return read.enum
  }
  return read.const === undefined ? null : [read.const]
}

function unreadable(reason: string): Unreadable {
  return { kind: "unreadable", reason }
}
