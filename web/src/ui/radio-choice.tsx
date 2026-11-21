import { Label } from "@/ui/label"
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group"
import { picked } from "./choices"

/** A choice a radio group or a select offers: its value, and the words shown for it. */
export type Choice<Value extends string> = Readonly<{
  value: Value
  label: string
}>

type RadioChoiceProps<Value extends string> = Readonly<{
  id: string
  label: string
  options: readonly Choice<Value>[]
  value: Value
  onChange: (value: Value) => void
  refusal?: string | null
}>

/** A choice of two or three short options in a form (web/DESIGN.md, Patterns, Import wizard and
 * Schema form): its label, in a field label's type and line, over a row of radios 24 px apart, each with its
 * own label, on a 40 px line beside the form's fields, where a toolbar's would be a segmented
 * control; a refusal of the choice turns the label to the negative and stands under the radios,
 * as a field's does (Forms), within 288 px, the width of the bar's timestamp's radios. */
export function RadioChoice<Value extends string>({
  id,
  label,
  options,
  value,
  onChange,
  refusal = null,
}: RadioChoiceProps<Value>) {
  return (
    <div
      className={
        refusal === null
          ? "flex flex-col gap-2"
          : "flex max-w-72 flex-col gap-2"
      }
    >
      <span
        id={`${id}-label`}
        className={
          refusal === null
            ? "text-sm leading-none font-medium text-foreground"
            : "text-sm leading-none font-medium text-negative"
        }
      >
        {label}
      </span>
      <RadioGroup
        aria-labelledby={`${id}-label`}
        aria-describedby={refusal === null ? undefined : `${id}-refusal`}
        value={value}
        onValueChange={(chosen) => onChange(picked(options, chosen))}
        className="flex h-10 items-center gap-6"
      >
        {options.map((option) => (
          <div key={option.value} className="flex items-center gap-2">
            <RadioGroupItem
              id={`${id}-${option.value}`}
              value={option.value}
              aria-invalid={refusal !== null}
            />
            <Label htmlFor={`${id}-${option.value}`}>{option.label}</Label>
          </div>
        ))}
      </RadioGroup>
      {refusal !== null && (
        <p id={`${id}-refusal`} className="text-negative">
          {refusal}
        </p>
      )}
    </div>
  )
}
