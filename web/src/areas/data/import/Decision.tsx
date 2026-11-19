import { cn } from "cn"
import { createContext, type ReactNode, useContext, useId } from "react"
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group"
import { picked } from "./choices"
import { stopLaterClick } from "./first-click"
import type { DecisionOption } from "./import-decisions"

/** The ids of a `Decision` box's title and message, which name and describe its radio list. */
const BoxWords = createContext<Readonly<{
  title: string
  message: string
}> | null>(null)

type OptionsProps<Value extends string> = Readonly<{
  label?: string
  options: readonly DecisionOption<Value>[]
  value: Value | null
  onChange: (value: Value) => void
  testId: string
}>

/** A decision's options (web/DESIGN.md, Patterns, Decision; D-106): a radio list named `label`,
 * or in a `Decision` box by the box's title and described by its message, none chosen where
 * `value` is none, each option a row chosen by a press anywhere on it, its radio beside its label
 * at 500 in heading text, which names the radio, and what it does under the label in body text,
 * which describes it; an option that waits is dimmed and chooses nothing. Changing one's mind is
 * choosing the other row; a double click's second click chooses nothing. */
export function Options<Value extends string>({
  label,
  options,
  value,
  onChange,
  testId,
}: OptionsProps<Value>) {
  const id = useId()
  const box = useContext(BoxWords)
  if (label === undefined && box === null) {
    throw new Error(
      "Expected a label for options outside a Decision box, got none."
    )
  }
  return (
    <RadioGroup
      aria-label={label}
      aria-labelledby={label === undefined ? box?.title : undefined}
      aria-describedby={label === undefined ? box?.message : undefined}
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
            className={cn(
              "flex items-start gap-3",
              option.disabled === true
                ? "cursor-not-allowed opacity-50"
                : "cursor-pointer"
            )}
            onClickCapture={stopLaterClick}
            data-testid={`${testId}-${option.value}`}
          >
            <RadioGroupItem
              id={item}
              value={option.value}
              disabled={option.disabled}
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
  holds: "options" | "action"
  testId: string
  children: ReactNode
}>

/** A decision the review asks (web/DESIGN.md, Patterns, Decision; D-106): a box on the control
 * surface with a hairline, padded 16 px, as the review's boxes of counts are, its title at 500
 * in heading text over what its files share and what to check in body text, then its options or
 * its one action, then its notes in subtle text at 12 px. A screen reader hears the title and
 * the message once: as the name and description of the options' radio list, or of the box, a
 * group, where it holds one action. */
export function Decision({
  title,
  message,
  notes = [],
  holds,
  testId,
  children,
}: DecisionProps) {
  const id = useId()
  const words = { title: `${id}-title`, message: `${id}-message` }
  const group =
    holds === "action"
      ? {
          role: "group",
          "aria-labelledby": words.title,
          "aria-describedby": words.message,
        }
      : {}
  return (
    <div
      {...group}
      className="flex flex-col gap-4 rounded-xl border bg-muted p-4"
      data-testid={testId}
    >
      <div className="flex flex-col gap-1">
        <p id={words.title} className="font-medium text-foreground">
          {title}
        </p>
        <p id={words.message} className="text-foreground-secondary">
          {message}
        </p>
      </div>
      <BoxWords.Provider value={words}>{children}</BoxWords.Provider>
      {notes.length > 0 && (
        <div className="flex flex-col gap-1 text-xs text-muted-foreground">
          {notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      )}
    </div>
  )
}
