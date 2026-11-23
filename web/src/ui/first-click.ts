import type { MouseEvent } from "react"

/** A press that acts on the first click alone, the keyboard's included, whose click counts
 * none, so that a double click acts once (web/DESIGN.md, Patterns, Import wizard). */
export function firstClick(act: () => void) {
  return (event: MouseEvent) => {
    if (event.detail <= 1) {
      act()
    }
  }
}

/** A double click's later clicks kept from choosing: once a change moves the rows above, the
 * second click of a quick double click lands on what the change moved under the pointer, such
 * as another option of a review's box (web/DESIGN.md, Patterns, Decision). */
export function stopLaterClick(event: MouseEvent) {
  if (event.detail > 1) {
    event.preventDefault()
  }
}
