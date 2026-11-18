import { type Dispatch, type RefObject, useEffect, useRef } from "react"
import { Button } from "@/ui/button"
import { counted } from "@/ui/figures"
import type { Draft, DraftChange } from "./import-draft"

type SkipFilesProps = Readonly<{
  toDecide: readonly string[]
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** Under a round's rows (web/DESIGN.md, Patterns, Review; D-105): while files that do not
 * import wait for a decision, how many, and Skip the files, which skips every one of them;
 * once none waits and some are skipped, that they stay out of the import until the files, the
 * layout, or the instrument change, and Skip none. A skip asks for no confirmation, since it writes nothing and one
 * click takes it back, and each button takes the focus from the other it replaces. */
export function SkipFiles({ toDecide, draft, change }: SkipFilesProps) {
  const [button, focusNext] = useFocusAfterPress()
  const skipped = draft.skipped
  if (toDecide.length > 0) {
    return (
      <div className="flex flex-col items-start gap-3" data-testid="skip-files">
        <p className="text-foreground-secondary">
          {waitingLine(toDecide.length)}
        </p>
        <Button
          key="skip"
          ref={button}
          variant="ghost"
          size="sm"
          onClick={() => {
            focusNext()
            change({ kind: "skipped", files: [...skipped, ...toDecide] })
          }}
        >
          {`Skip the ${counted(toDecide.length, "file")}`}
        </Button>
      </div>
    )
  }
  if (skipped.length === 0) {
    return null
  }
  return (
    <div className="flex flex-col items-start gap-3" data-testid="skip-files">
      <p className="text-foreground-secondary">
        {skipped.length === 1
          ? "The skipped file stays out of this import until you change the files, the layout, or the instrument."
          : `The ${counted(skipped.length, "skipped file")} stay out of this import until you change the files, the layout, or the instrument.`}
      </p>
      <Button
        key="skip none"
        ref={button}
        variant="ghost"
        size="sm"
        onClick={() => {
          focusNext()
          change({ kind: "skipped", files: [] })
        }}
      >
        Skip none
      </Button>
    </div>
  )
}

function waitingLine(files: number): string {
  return files === 1
    ? "1 file does not import as it is read: correct it, or skip it to import the others."
    : `${counted(files, "file")} do not import as they are read: correct them, or skip them to import the others.`
}

type SkipFileProps = Readonly<{
  file: string
  draft: Draft
  change: Dispatch<DraftChange>
}>

/** At the foot of the review of a round's file that does not import, or that was skipped
 * (D-105): Skip this file, or once skipped, Do not skip, each taking the focus from the other
 * it replaces. */
export function SkipFile({ file, draft, change }: SkipFileProps) {
  const [button, focusNext] = useFocusAfterPress()
  const skipped = draft.skipped
  const isSkipped = skipped.includes(file)
  return (
    <Button
      key={isSkipped ? "do not skip" : "skip"}
      ref={button}
      variant="ghost"
      size="sm"
      className="self-start"
      onClick={() => {
        focusNext()
        change({
          kind: "skipped",
          files: isSkipped
            ? skipped.filter((each) => each !== file)
            : [...skipped, file],
        })
      }}
    >
      {isSkipped ? "Do not skip" : "Skip this file"}
    </Button>
  )
}

/** The button a press replaces, and the way to give it the focus once it is drawn after that
 * press alone, so that a change made elsewhere, such as a skip in a file's row, never moves the
 * focus here; where the press leaves no button, as Skip none does once no file waits, the focus
 * goes to the frame the button stood in, the review's, rather than to the page. */
function useFocusAfterPress(): readonly [
  RefObject<HTMLButtonElement | null>,
  () => void,
] {
  const button = useRef<HTMLButtonElement>(null)
  const pressed = useRef(false)
  const frame = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!pressed.current) {
      return
    }
    pressed.current = false
    const target = button.current === null ? frame.current : button.current
    target?.focus()
  })
  return [
    button,
    () => {
      pressed.current = true
      frame.current =
        button.current === null
          ? null
          : button.current.closest<HTMLElement>("[tabindex='-1']")
    },
  ]
}
