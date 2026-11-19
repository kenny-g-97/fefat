import { type RefObject, useEffect, useRef } from "react"

/** The button a press replaces, and the way to give it the focus once it is drawn after that
 * press alone, so that a change made elsewhere, such as a skip in a file's row, never moves the
 * focus here; where the press leaves no button, the focus goes to the step's card it stood in,
 * a group named for its step, rather than to the page. */
export function useFocusAfterPress(): readonly [
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
          : button.current.closest<HTMLElement>("[role='group'][tabindex='-1']")
    },
  ]
}
