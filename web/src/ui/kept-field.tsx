import { useState } from "react"
import { Input } from "@/ui/input"

type KeptFieldProps = Readonly<{
  id: string
  value: string
  onKeep: (value: string) => void
  placeholder?: string
  invalid?: boolean
  describedBy?: string
  className?: string
}>

/** A text field whose text is kept once the field is left or on Enter, as the chart's contract
 * field keeps its own (web/DESIGN.md, Patterns, Live draft), so that nothing half typed is
 * acted on; a value changed from outside replaces the typed text. */
export function KeptField({
  id,
  value,
  onKeep,
  placeholder,
  invalid = false,
  describedBy,
  className,
}: KeptFieldProps) {
  const [typed, setTyped] = useState(value)
  const [given, setGiven] = useState(value)
  if (given !== value) {
    setGiven(value)
    setTyped(value)
  }
  const keep = () => {
    if (typed !== value) {
      onKeep(typed)
    }
  }
  return (
    <Input
      id={id}
      value={typed}
      placeholder={placeholder}
      autoComplete="off"
      spellCheck={false}
      aria-invalid={invalid}
      aria-describedby={describedBy}
      className={className}
      onChange={(event) => setTyped(event.target.value)}
      onBlur={keep}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault()
          keep()
        }
      }}
    />
  )
}
