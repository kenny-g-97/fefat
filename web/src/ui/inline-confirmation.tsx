import { useState } from "react"
import { Button } from "@/ui/button"

type InlineConfirmationProps = Readonly<{
  trigger: string
  confirm: string
  pending?: boolean
  onConfirm: () => void
}>

type Asking = "not asked" | "confirming" | "kept"

/** An action that cannot be undone, asked once in place (web/DESIGN.md, Patterns, Inline
 * confirmation): the trigger gives way to Keep, focused, with the confirm beside it as the
 * danger action, so that a double click keeps, and the trigger takes the focus back once Keep
 * is pressed. */
export function InlineConfirmation({
  trigger,
  confirm,
  pending = false,
  onConfirm,
}: InlineConfirmationProps) {
  const [asking, setAsking] = useState<Asking>("not asked")
  if (asking === "confirming") {
    return (
      <div className="flex justify-end gap-2">
        <Button
          variant="destructive"
          size="sm"
          disabled={pending}
          onClick={onConfirm}
        >
          {confirm}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          autoFocus
          onClick={() => setAsking("kept")}
        >
          Keep
        </Button>
      </div>
    )
  }
  return (
    <Button
      variant="ghost"
      size="sm"
      autoFocus={asking === "kept"}
      onClick={() => setAsking("confirming")}
    >
      {trigger}
    </Button>
  )
}
