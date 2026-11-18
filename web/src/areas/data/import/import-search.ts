import { z } from "zod"
import type { ListedProfile } from "@/api/imports"
import { datasetSearch } from "../chart-search"
import type { Card } from "./import-draft"

/** The import wizard's steps in their order, a card each and the review last (web/DESIGN.md,
 * Patterns, Import wizard; D-105), as the address names them. */
export const STEPS = [
  "file",
  "layout",
  "instrument",
  "review",
] as const satisfies readonly (Card | "review")[]

export type Step = (typeof STEPS)[number]

/** The import page's search parameters (step 5.12): the preset a source's Import names, the
 * page it was opened from, which its back link leads to, and for a dataset's Import more data
 * the dataset's instrument and provider; and the wizard's step shown, so that the browser's
 * Back moves between steps (D-105), File where it names none. A value the page cannot read is
 * left out. */
export const importSearch = datasetSearch.extend({
  preset: z
    .string()
    .regex(/^[A-Za-z0-9._-]{1,64}$/)
    .optional()
    .catch(undefined),
  from: z.enum(["dataset", "sources"]).optional().catch(undefined),
  step: z.enum(STEPS).optional().catch(undefined),
})

export type ImportSearch = z.infer<typeof importSearch>

/** Where the import page leads back to: the Data page, the sources page, or a dataset's. */
export type Back =
  | Readonly<{ kind: "data" }>
  | Readonly<{ kind: "sources" }>
  | Readonly<{ kind: "dataset"; instrument: string; provider: string }>

/** The page `search` says the import page was opened from; the Data page where it names none,
 * or a dataset without its instrument and provider. */
export function backOf(search: ImportSearch): Back {
  if (search.from === "sources") {
    return { kind: "sources" }
  }
  const { instrument, provider } = search
  if (
    search.from === "dataset" &&
    instrument !== undefined &&
    provider !== undefined
  ) {
    return { kind: "dataset", instrument, provider }
  }
  return { kind: "data" }
}

/** What a preset in the address chooses: Databento's batch downloads, which its importer
 * reads, a profile of that name, else the one profile the trader saved for that provider. */
export type PresetChoice =
  | Readonly<{ kind: "none" }>
  | Readonly<{ kind: "batch" }>
  | Readonly<{ kind: "profile"; name: string }>

/** The preset Databento's batch downloads go by, the importer of step 1.6 rather than a
 * profile. */
export const BATCH_PRESET = "databento"

/** What `preset` chooses among `profiles` (`PresetChoice`): nothing where it names none, or
 * none or several of the trader's saved profiles. */
export function presetChoice(
  preset: string | undefined,
  profiles: readonly ListedProfile[]
): PresetChoice {
  if (preset === undefined) {
    return { kind: "none" }
  }
  if (preset === BATCH_PRESET) {
    return { kind: "batch" }
  }
  if (profiles.some((listed) => listed.profile.name === preset)) {
    return { kind: "profile", name: preset }
  }
  const saved = profiles.filter(
    (listed) => listed.origin === "saved" && listed.profile.provider === preset
  )
  const [only] = saved
  return saved.length === 1 && only !== undefined
    ? { kind: "profile", name: only.profile.name }
    : { kind: "none" }
}
