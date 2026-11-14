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
  className?: string
  children: ReactNode
}>

/** A field of a toolbar under its label (web/DESIGN.md, Patterns, Forms), which names the field
 * with `id`. */
export function Choice({ id, label, className, children }: ChoiceProps) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  )
}

type PickerProps = Readonly<{
  id: string
  value: string
  options: readonly Option[]
  onChange: (value: string) => void
  className?: string
}>

/** The data area's select (web/DESIGN.md, Patterns, Select): one choice among many, its list a
 * popper under its trigger, 144 px wide where its values need no more. */
export function Picker({
  id,
  value,
  options,
  onChange,
  className = "w-36",
}: PickerProps) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} className={className}>
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
  )
}
