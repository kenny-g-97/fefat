import { useRef, useState } from "react"
import { Button } from "@/ui/button"

type FileDropProps = Readonly<{
  id: string
  disabled?: boolean
  onFile: (file: File) => void
}>

/** Where a file is chosen (web/DESIGN.md, Patterns, File drop): Choose a file opens the
 * browser's own picker, by the pointer or the keys, and a file dropped on the box is taken
 * too, the box taking the brand's line while one is dragged over it. */
export function FileDrop({ id, disabled = false, onFile }: FileDropProps) {
  const picker = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
    <div
      data-slot="file-drop"
      data-over={over}
      onDragOver={(event) => {
        event.preventDefault()
        setOver(!disabled)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        const [file] = event.dataTransfer.files
        if (!disabled && file !== undefined) {
          onFile(file)
        }
      }}
      className="flex min-h-24 items-center gap-4 rounded-xl border border-dashed bg-muted px-6"
    >
      <Button
        type="button"
        variant="ghost"
        disabled={disabled}
        onClick={() => picker.current?.click()}
      >
        Choose a file
      </Button>
      <span className="text-foreground-secondary">or drop it here</span>
      <input
        ref={picker}
        id={id}
        type="file"
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        onChange={(event) => {
          const [file] = event.target.files ?? []
          event.target.value = ""
          if (file !== undefined) {
            onFile(file)
          }
        }}
      />
    </div>
  )
}
