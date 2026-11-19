import { type ReactNode, useId } from "react"
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group"
import { picked } from "./choices"

/** An option of a decision: its value, its label, named by what happens to the files, and what
 * it does. */
export type DecisionOption<Value extends string> = Readonly<{
  value: Value
  label: string
  description: string
}>

type OptionsProps<Value extends string> = Readonly<{
  label: string
  options: readonly DecisionOption<Value>[]
  value: Value | null
  onChange: (value: Value) => void
  testId: string
}>

/** A decision's options (web/DESIGN.md, Patterns, Decision; D-106): a radio list named
 * `label`, none chosen where `value` is none, each option a row chosen by a press anywhere on
 * it, its radio beside its label at 500 in heading text, which names the radio, and what it
 * does under the label in body text, which describes it. Changing one's mind is choosing the
 * other row. */
export function Options<Value extends string>({
  label,
  options,
  value,
  onChange,
  testId,
}: OptionsProps<Value>) {
  const id = useId()
  return (
    <RadioGroup
      aria-label={label}
      value={value}
      onValueChange={(chosen) => onChange(picked(options, chosen))}
      className="flex flex-col gap-3"
      data-testid={testId}
    >
      {options.map((option) => {
        const item = `${id}-${option.value}`
        return (
          <label
            key={option.value}
            htmlFor={item}
            className="flex cursor-pointer items-start gap-3"
            data-testid={`${testId}-${option.value}`}
          >
            <RadioGroupItem
              id={item}
              value={option.value}
              aria-labelledby={`${item}-label`}
              aria-describedby={`${item}-description`}
              className="mt-0.5"
            />
            <span className="flex flex-col gap-0.5">
              <span
                id={`${item}-label`}
                className="font-medium text-foreground"
              >
                {option.label}
              </span>
              <span
                id={`${item}-description`}
                className="text-foreground-secondary"
              >
                {option.description}
              </span>
            </span>
          </label>
        )
      })}
    </RadioGroup>
  )
}

type DecisionProps = Readonly<{
  title: string
  message: string
  notes?: readonly string[]
  testId: string
  children: ReactNode
}>

/** A decision the review asks (web/DESIGN.md, Patterns, Decision; D-106): a box on the control
 * surface with a hairline, padded 16 px, as the review's boxes of counts are, its title at 500
 * in heading text over what its files share and what to check in body text, then its options or
 * its one action, then its notes in subtle text at 12 px. */
export function Decision({
  title,
  message,
  notes = [],
  testId,
  children,
}: DecisionProps) {
  return (
    <div
      className="flex flex-col gap-4 rounded-xl border bg-muted p-4"
      data-testid={testId}
    >
      <div className="flex flex-col gap-1">
        <p className="font-medium text-foreground">{title}</p>
        <p className="text-foreground-secondary">{message}</p>
      </div>
      {children}
      {notes.map((note) => (
        <p key={note} className="text-xs text-muted-foreground">
          {note}
        </p>
      ))}
    </div>
  )
}
