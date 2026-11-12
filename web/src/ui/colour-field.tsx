import { useEffect, useRef } from "react"
import { Button } from "./button"

type ColourFieldProps = Readonly<{
  id: string
  label: string
  colour: string
  own: boolean
  onPreview: (colour: string) => void
  onKeep: (colour: string) => void
  onReset: () => void
}>

/** A colour the trader picks (web/DESIGN.md, Patterns, Colour field): the browser's own colour
 * field, which shows each colour as it is dragged and keeps the last once its picker closes,
 * and, while the colour is the trader's own, a way back to the theme's. */
export function ColourField({
  id,
  label,
  colour,
  own,
  onPreview,
  onKeep,
  onReset,
}: ColourFieldProps) {
  const field = useRef<HTMLInputElement>(null)
  // React's onChange is the field's every input; its change comes once, when the picker closes.
  useEffect(() => {
    const input = field.current
    if (input === null) {
      return
    }
    const keep = () => onKeep(input.value)
    input.addEventListener("change", keep)
    return () => input.removeEventListener("change", keep)
  }, [onKeep])

  return (
    <div className="flex h-10 items-center gap-3">
      <input
        ref={field}
        id={id}
        type="color"
        value={colour}
        data-slot="colour-field"
        onChange={(event) => onPreview(event.target.value)}
      />
      <label htmlFor={id} className="flex-1 font-medium">
        {label}
      </label>
      {own ? (
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Reset ${label.toLowerCase()} to the theme's`}
          onClick={onReset}
        >
          Reset
        </Button>
      ) : (
        <span className="text-xs text-muted-foreground">Theme's</span>
      )}
    </div>
  )
}
