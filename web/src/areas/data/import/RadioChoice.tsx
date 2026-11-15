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
}>

/** A choice of two or three short options in a form (web/DESIGN.md, Patterns, Overlays): its
 * label over a row of radios 24 px apart, each with its own label, on a 40 px line beside the
 * form's fields, where a toolbar's would be a segmented control. */
export function RadioChoice<Value extends string>({
  id,
  label,
  options,
  value,
  onChange,
}: RadioChoiceProps<Value>) {
  return (
    <div className="flex flex-col gap-2">
      <span id={`${id}-label`} className="font-medium text-foreground">
        {label}
      </span>
      <RadioGroup
        aria-labelledby={`${id}-label`}
        value={value}
        onValueChange={(chosen) => onChange(picked(options, chosen))}
        className="flex h-10 items-center gap-6"
      >
        {options.map((option) => (
          <div key={option.value} className="flex items-center gap-2">
            <RadioGroupItem id={`${id}-${option.value}`} value={option.value} />
            <Label htmlFor={`${id}-${option.value}`}>{option.label}</Label>
          </div>
        ))}
      </RadioGroup>
    </div>
  )
}
