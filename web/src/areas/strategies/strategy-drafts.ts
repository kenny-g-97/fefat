import { useState } from "react"
import { z } from "zod"

/** What the trader edits of a version before saving it as the next: its code, its hypothesis,
 * and its changelog. */
export type StrategyDraft = Readonly<{
  code: string
  hypothesis: string
  changelog: string
}>

const KEPT_PREFIX = "fefat_strategy_draft"
const keptDraft = z.object({
  code: z.string(),
  hypothesis: z.string(),
  changelog: z.string(),
})

/** The local storage key of the draft of version `version` of the strategy `name`, which a
 * strategy's name addresses, since its id changes at an index's rebuild. */
export function draftKey(name: string, version: number): string {
  return `${KEPT_PREFIX}:${name}:${version}`
}

/** The draft `text` holds, as this browser's local storage kept it; none where nothing is kept,
 * or where what is kept is no draft: the storage is the trader's to edit, and another version of
 * FEAT's to have written. */
export function storedDraft(text: string | null): StrategyDraft | null {
  if (text === null) {
    return null
  }
  const read = keptDraft.safeParse(parsed(text))
  return read.success ? read.data : null
}

/** The draft of version `version` of the strategy `name`: what this browser kept of it, or else
 * the version as `saved`, and the ways to change it and to discard it. A draft is kept while its
 * code differs from the version's, and forgotten once it does not and once discarded; a save
 * forgets it (`forgetDraft`). A browser that refuses its storage keeps the draft for the visit. */
export function useStrategyDraft(
  name: string,
  version: number,
  saved: StrategyDraft
) {
  const key = draftKey(name, version)
  const [draft, setDraft] = useState(() => {
    const kept = keptText(key)
    return kept === null ? saved : kept
  })
  const change = (next: StrategyDraft) => {
    setDraft(next)
    if (next.code === saved.code) {
      forgetDraft(name, version)
      return
    }
    keep(key, next)
  }
  const discard = () => {
    forgetDraft(name, version)
    setDraft(saved)
  }
  return { draft, change, discard }
}

/** Forget the draft of version `version` of the strategy `name`, as its save does. */
export function forgetDraft(name: string, version: number): void {
  try {
    localStorage.removeItem(draftKey(name, version))
  } catch {
    // A browser that refuses its storage kept nothing to forget.
  }
}

function keptText(key: string): StrategyDraft | null {
  try {
    return storedDraft(localStorage.getItem(key))
  } catch {
    // A browser that refuses its storage, as a private window may, keeps nothing.
    return null
  }
}

function keep(key: string, draft: StrategyDraft): void {
  try {
    localStorage.setItem(key, JSON.stringify(draft))
  } catch {
    // Storage refused or full: the draft holds in the page until it is left.
  }
}

function parsed(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}
