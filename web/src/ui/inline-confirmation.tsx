import { useState } from "react"
import { Button } from "@/ui/button"

type InlineConfirmationProps = Readonly<{
  trigger: string
  confirm: string
  pending?: boolean
  align?: "start" | "end"
  focused?: boolean
  onConfirm: () => void
}>

type Asking =
  | Readonly<{ kind: "not asked" }>
  | Readonly<{ kind: "confirming"; width: number }>
  | Readonly<{ kind: "kept" }>

/** An action that cannot be undone, asked once in place (web/DESIGN.md, Patterns, Inline
 * confirmation): the trigger gives way to Keep, focused, in the trigger's place and at least its
 * width, with the confirm beside it as the danger action, so that a double click keeps; Keep
 * stands first where the trigger starts its line, `align="start"`, its label where the
 * trigger's began, and last where it ends it, and the trigger takes the focus back once Keep is
 * pressed, or as it appears where `focused`, as after the way back of a confirmed choice. */
export function InlineConfirmation({
  trigger,
  confirm,
  pending = false,
  align = "end",
  focused = false,
  onConfirm,
}: InlineConfirmationProps) {
  const [asking, setAsking] = useState<Asking>(
    focused ? { kind: "kept" } : { kind: "not asked" }
  )
  if (asking.kind === "confirming") {
    const keep = (
      <Button
        variant="ghost"
        size="sm"
        autoFocus
        style={{
          minWidth: asking.width,
          justifyContent: align === "start" ? "flex-start" : "center",
        }}
        onClick={() => setAsking({ kind: "kept" })}
      >
        Keep
      </Button>
    )
    const confirmButton = (
      <Button
        variant="destructive"
        size="sm"
        disabled={pending}
        onClick={onConfirm}
      >
        {confirm}
      </Button>
    )
    return align === "start" ? (
      <div className="flex gap-2">
        {keep}
        {confirmButton}
      </div>
    ) : (
      <div className="flex justify-end gap-2">
        {confirmButton}
        {keep}
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
