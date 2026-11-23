import type { Dispatch } from "react"
import { Button } from "@/ui/button"
import { firstClick } from "@/ui/first-click"
import { useFocusAfterPress } from "./focus-after-press"
import type { Draft, DraftChange } from "./import-draft"

type SkipFileProps = Readonly<{
  file: string
  offered: boolean
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** At the foot of the review of a round's file that does not import, or that was skipped
 * (D-105): Skip this file, or once skipped, Do not skip, each taking the focus from the other
 * it replaces, and acting on a double click's first click alone. It stays drawn while not
 * `offered`, showing nothing, so that a press that ends the offer, such as Do not skip for a file
 * that imports by then, still hands the focus on. */
export function SkipFile({ file, offered, draft, change }: SkipFileProps) {
  const [button, focusNext] = useFocusAfterPress()
  const skipped = draft.skipped
  const isSkipped = skipped.includes(file)
  if (!offered) {
    return null
  }
  return (
    <Button
      key={isSkipped ? "do not skip" : "skip"}
      ref={button}
      variant="ghost"
      size="sm"
      className="self-start"
      onClick={firstClick(() => {
        focusNext()
        change({
          kind: "skipped",
          files: isSkipped
            ? skipped.filter((each) => each !== file)
            : [...skipped, file],
        })
      })}
    >
      {isSkipped ? "Do not skip" : "Skip this file"}
    </Button>
  )
}
