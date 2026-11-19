import { useState } from "react"
import { Button } from "@/ui/button"

type InlineConfirmationProps = Readonly<{
  trigger: string
  confirm: string
  pending?: boolean
  onConfirm: () => void
}>

type Asking =
  | Readonly<{ kind: "not asked" }>
  | Readonly<{ kind: "confirming"; width: number }>
  | Readonly<{ kind: "kept" }>

/** An action that cannot be undone, asked once in place (web/DESIGN.md, Patterns, Inline
 * confirmation): the trigger gives way to Keep, focused, in the trigger's place and at least its
 * width, with the confirm before it as the danger action, so that a double click keeps, and the
 * trigger takes the focus back once Keep is pressed. Both wait while the confirm's request
 * runs, since what it asked for can no longer be kept (step 5.18). */
export function InlineConfirmation({
  trigger,
  confirm,
  pending = false,
  onConfirm,
}: InlineConfirmationProps) {
  const [asking, setAsking] = useState<Asking>({ kind: "not asked" })
  if (asking.kind === "confirming") {
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
          disabled={pending}
          style={{ minWidth: asking.width }}
          onClick={() => setAsking({ kind: "kept" })}
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
      autoFocus={asking.kind === "kept"}
      onClick={(event) =>
        setAsking({
          kind: "confirming",
          width: event.currentTarget.offsetWidth,
        })
      }
    >
      {trigger}
    </Button>
  )
}
