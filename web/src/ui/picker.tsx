import { cn } from "cn"
import type { ReactNode } from "react"
import { Label } from "@/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/ui/select"

/** A choice a select offers: its value, and the words the list shows for it. */
export type Option = Readonly<{ value: string; label: string }>

type ChoiceProps = Readonly<{
  id: string
  label: string
  refusal?: string | null
  className?: string
  children: ReactNode
}>

/** A field of a toolbar under its label (web/DESIGN.md, Patterns, Forms), which names the field
 * with `id`; a refusal of what the field holds turns the label to the negative and stands
 * under the field at `<id>-refusal`, for the field to name, as wide as `className` makes the
 * choice, the field's own width. */
export function Choice({
  id,
  label,
  refusal = null,
  className,
  children,
}: ChoiceProps) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Label
        htmlFor={id}
        className={refusal === null ? undefined : "text-negative"}
      >
        {label}
      </Label>
      {children}
      {refusal !== null && (
        <p id={`${id}-refusal`} className="text-negative">
          {refusal}
        </p>
      )}
    </div>
  )
}

type PickerProps = Readonly<{
  id: string
  value: string
  options: readonly Option[]
  onChange: (value: string) => void
  placeholder?: string
  label?: string
  shown?: string
  size?: "sm" | "default"
  className?: string
}>

/** The app's select (web/DESIGN.md, Patterns, Select): one choice among many, its list a
 * popper under its trigger, 144 px wide where its values need no more; with no value chosen,
 * `""`, it shows `placeholder` in subtle text, and with one, the chosen option's words, or
 * `shown` where the list's words are longer than the trigger holds. A select over a table's
 * column is `sm`, 32 px, and named by `label`, since no label element names it. */
export function Picker({
  id,
  value,
  options,
  onChange,
  placeholder,
  label,
  shown,
  size = "default",
  className = "w-36",
}: PickerProps) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        id={id}
        size={size}
        className={className}
        aria-label={label}
      >
        <SelectValue placeholder={placeholder}>
          {value === "" ? undefined : shown}
        </SelectValue>
      </SelectTrigger>
      <SelectContent position="popper">
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
