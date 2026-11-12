import { z } from "zod"
import { timeframe } from "@/api/bar-windows"

/** A root's or a contract's name as the store keeps it, a folder name
 * (`fefat.market.layout.FolderName`): letters and digits, with dots, dashes, and underscores
 * inside. */
const FOLDER_NAME = /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$/

/** The chart page's search parameters (step 5.4): the root, a contract of it to chart alone,
 * the timeframe, adjusted or raw prices, and the provider, the catalog's recommended source
 * among those that hold the root when left out; a value the page cannot read is its default. */
export const chartSearch = z.object({
  instrument: z.string().regex(FOLDER_NAME).optional().catch(undefined),
  contract: z.string().regex(FOLDER_NAME).optional().catch(undefined),
  timeframe: timeframe.default("5m").catch("5m"),
  prices: z.enum(["adjusted", "raw"]).default("adjusted").catch("adjusted"),
  provider: z
    .string()
    .regex(/^[A-Za-z0-9._-]{1,64}$/)
    .optional()
    .catch(undefined),
})

export type ChartSearch = z.infer<typeof chartSearch>
