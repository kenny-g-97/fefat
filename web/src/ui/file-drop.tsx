import { useRef, useState } from "react"
import { Button } from "@/ui/button"

type FileDropProps = Readonly<{
  id: string
  disabled?: boolean
  onFiles: (files: readonly File[]) => void
}>

/** Where files are chosen (web/DESIGN.md, Patterns, File drop): Choose files opens the
 * browser's own picker, by the pointer or the keys, where one or several are chosen, and files
 * dropped on the box are taken too, the box taking the brand's line while they are dragged
 * over it. */
export function FileDrop({ id, disabled = false, onFiles }: FileDropProps) {
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
        const files = [...event.dataTransfer.files]
        if (!disabled && files.length > 0) {
          onFiles(files)
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
        Choose files
      </Button>
      <span className="text-foreground-secondary">or drop them here</span>
      <input
        ref={picker}
        id={id}
        type="file"
        multiple
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        onChange={(event) => {
          const files = [...(event.target.files ?? [])]
          event.target.value = ""
          if (files.length > 0) {
            onFiles(files)
          }
        }}
      />
    </div>
  )
}
