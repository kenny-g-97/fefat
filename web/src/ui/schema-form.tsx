import { type ReactNode, useState } from "react"
import { Input } from "./input"
import { Label } from "./label"
import { RadioChoice } from "./radio-choice"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select"
import {
  defaultEntries,
  type EnteredValues,
  enteredValue,
  type ParameterField,
  type ParameterValue,
  parameterFields,
  parameterValues,
  typedValue,
} from "./schema-fields"

type SchemaFormProps = Readonly<{
  schema: unknown
  idPrefix: string
  onChange?: (values: Readonly<Record<string, ParameterValue>> | null) => void
}>

const FLAGS = [
  { value: "true", label: "True" },
  { value: "false", label: "False" },
]

/** A form drawn from a JSON schema of parameters (web/DESIGN.md, Patterns, Schema form): a field
 * for each parameter, named as the code writes it, at its default, a number or a word typed and
 * checked when the field is left, a flag or one of a few values a radio group, more values a
 * select; `onChange` gets the values as a run would take them, or null while one is refused. The
 * strategy page draws a version's parameters with it (step 5.5); the builder's execution template,
 * the combinations, and the prop rules of Phases 6 and 7 after it. */
export function SchemaForm({ schema, idPrefix, onChange }: SchemaFormProps) {
  const reading = parameterFields(schema)
  if (reading.kind === "unreadable") {
    return (
      <p role="alert" className="text-negative">
        {reading.reason}
      </p>
    )
  }
  if (reading.fields.length === 0) {
    return <p className="text-foreground-secondary">It takes no parameters.</p>
  }
  // Other fields, defaults, or choices start afresh, as a schema the page changes in place gives.
  return (
    <SchemaFields
      key={JSON.stringify(reading.fields)}
      fields={reading.fields}
      idPrefix={idPrefix}
      onChange={onChange}
    />
  )
}

type SchemaFieldsProps = Readonly<{
  fields: readonly ParameterField[]
  idPrefix: string
  onChange?: (values: Readonly<Record<string, ParameterValue>> | null) => void
}>

function SchemaFields({ fields, idPrefix, onChange }: SchemaFieldsProps) {
  const [entered, setEntered] = useState<EnteredValues>(() =>
    defaultEntries(fields)
  )
  const [left, setLeft] = useState<ReadonlySet<string>>(() => new Set())
  const enter = (name: string, value: ParameterValue) => {
    const next = new Map(entered).set(name, value)
    setEntered(next)
    onChange?.(parameterValues(fields, next))
  }
  return (
    <div className="flex flex-col gap-5">
      {fields.map((field) => (
        <ParameterInput
          key={field.name}
          field={field}
          id={`${idPrefix}-${field.name}`}
          value={enteredValue(entered, field.name)}
          left={left.has(field.name)}
          onEnter={(value) => enter(field.name, value)}
          onLeave={() => setLeft(new Set(left).add(field.name))}
        />
      ))}
    </div>
  )
}

type ParameterInputProps = Readonly<{
  field: ParameterField
  id: string
  value: ParameterValue
  left: boolean
  onEnter: (value: ParameterValue) => void
  onLeave: () => void
}>

function ParameterInput({
  field,
  id,
  value,
  left,
  onEnter,
  onLeave,
}: ParameterInputProps) {
  if (field.kind === "boolean") {
    return (
      <Described description={field.description}>
        <RadioChoice
          id={id}
          label={field.name}
          options={FLAGS}
          value={value === true ? "true" : "false"}
          onChange={(chosen) => onEnter(chosen === "true")}
        />
      </Described>
    )
  }
  if (field.kind === "choice") {
    const options = field.options.map((option) => ({
      value: String(option),
      label: String(option),
    }))
    const chosen = (text: string) => onEnter(optionOf(field.options, text))
    return (
      <Described description={field.description}>
        {options.length <= 3 ? (
          <RadioChoice
            id={id}
            label={field.name}
            options={options}
            value={String(value)}
            onChange={chosen}
          />
        ) : (
          <div className="flex flex-col gap-2">
            <Label htmlFor={id}>{field.name}</Label>
            <Select value={String(value)} onValueChange={chosen}>
              <SelectTrigger id={id} className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper">
                {options.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </Described>
    )
  }
  const read = typedValue(field.kind, String(value), field.initial)
  const refusal = left && read.kind === "refused" ? read.message : null
  return (
    <div className="flex flex-col gap-2">
      <Label
        htmlFor={id}
        className={refusal === null ? undefined : "text-negative"}
      >
        {field.name}
      </Label>
      <Input
        id={id}
        value={String(value)}
        inputMode={INPUT_MODES[field.kind]}
        autoComplete="off"
        spellCheck={false}
        aria-invalid={refusal !== null}
        aria-describedby={refusal === null ? undefined : `${id}-refusal`}
        className="w-48"
        onChange={(event) => onEnter(event.target.value)}
        onBlur={onLeave}
      />
      {field.description !== null && (
        <p className="text-xs text-muted-foreground">{field.description}</p>
      )}
      {refusal !== null && (
        <p id={`${id}-refusal`} className="text-negative">
          {refusal}
        </p>
      )}
    </div>
  )
}

/** A choice with the parameter's description under it, where it has one. */
function Described({
  description,
  children,
}: Readonly<{ description: string | null; children: ReactNode }>) {
  if (description === null) {
    return children
  }
  return (
    <div className="flex flex-col gap-2">
      {children}
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  )
}

const INPUT_MODES = {
  integer: "numeric",
  number: "decimal",
  string: "text",
} satisfies Readonly<
  Record<"integer" | "number" | "string", "numeric" | "decimal" | "text">
>

/** The value of `options` whose text is `text`, as a radio or a select gives it back. */
function optionOf(
  options: readonly ParameterValue[],
  text: string
): ParameterValue {
  const found = options.find((option) => String(option) === text)
  if (found === undefined) {
    throw new Error(`Expected one of ${options.join(", ")}, got ${text}.`)
  }
  return found
}
