import { useEffect, useRef, useState } from "react"
import { Button } from "@/ui/button"

type InlineConfirmationProps = Readonly<{
  trigger: string
  confirm: string
  pending?: boolean
  size?: "sm" | "default"
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
 * runs, since what it asked for can no longer be kept (step 5.18), and the confirm takes the
 * focus back once a request it refused ends, which its wait dropped. Its buttons are 32 px in a
 * table's row, and 40 px standing in a card (`size`). */
export function InlineConfirmation({
  trigger,
  confirm,
  pending = false,
  size = "sm",
  onConfirm,
}: InlineConfirmationProps) {
  const [asking, setAsking] = useState<Asking>({ kind: "not asked" })
  const confirmButton = useRef<HTMLButtonElement>(null)
  const waited = useRef(pending)
  useEffect(() => {
    if (waited.current && !pending && asking.kind === "confirming") {
      confirmButton.current?.focus()
    }
    waited.current = pending
  }, [pending, asking.kind])
  if (asking.kind === "confirming") {
    return (
      <div className="flex justify-end gap-2">
        <Button
          ref={confirmButton}
          variant="destructive"
          size={size}
          disabled={pending}
          onClick={onConfirm}
        >
          {confirm}
        </Button>
        <Button
          variant="ghost"
          size={size}
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
      size={size}
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
