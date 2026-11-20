import { z } from "zod"

/** A strategy's name as the server keeps it (`fefat.strategy.versions.STRATEGY_NAME`), the name
 * of its folder: a lower-case identifier of at most 64 characters, lower-case since Windows takes
 * `Breakout` and `breakout` for one folder. A test holds it equal to the API's. */
export const STRATEGY_NAME = /^[a-z][a-z0-9_]{0,63}$/

/** The names Windows keeps for its devices, which no folder takes. */
const DEVICE_NAMES: ReadonlySet<string> = new Set([
  "con",
  "prn",
  "aux",
  "nul",
  ...["com", "lpt"].flatMap((port) =>
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `${port}${n}`)
  ),
])

/** A new strategy's name, checked as the server checks it. */
export const strategyName = z
  .string()
  .regex(
    STRATEGY_NAME,
    "Use 1 to 64 lower-case letters, digits, or underscores, starting with a letter."
  )
  .refine(
    (name) => !DEVICE_NAMES.has(name),
    "Windows keeps that name for a device. Choose another name."
  )

/** The page of a strategy's version, which its name and its number address (step 5.5): an
 * index's rebuild gives a strategy another id, its name never. A version left out is the
 * latest; a value the page cannot read is left out. */
export const strategySearch = z.object({
  name: z.string().regex(STRATEGY_NAME).optional().catch(undefined),
  version: z.number().int().min(1).optional().catch(undefined),
})

export type StrategySearch = z.infer<typeof strategySearch>
