import { z } from "zod"
import type { components } from "@/api/schema"
import { isTradeDate } from "@/ui/trade-date"

/** The statuses a run takes, its job's until it is saved. */
export const RUN_STATUSES = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
] as const

/** What the Runs page's filters ask, kept in its address so that a reload, the way back from a
 * run, and a link keep them; a value the page cannot read is left out. A strategy's name, or
 * `versioned` false for the runs that name no saved version. */
export const runsSearch = z.object({
  strategy: z.string().min(1).max(64).optional().catch(undefined),
  versioned: z.literal(false).optional().catch(undefined),
  status: z.enum(RUN_STATUSES).optional().catch(undefined),
})

export type RunsSearch = z.infer<typeof runsSearch>

/** A run's page: a saved run by its key, which a rebuild of the index keeps, or a submission by
 * its row's id with its job, whose result names the run should its row give way to another. */
export const runSearch = z.object({
  key: z
    .string()
    .regex(/^[0-9a-f]{64}$/)
    .optional()
    .catch(undefined),
  id: z.string().min(1).max(64).optional().catch(undefined),
  job: z.string().min(1).max(64).optional().catch(undefined),
})

/** The fewest and the most runs a comparison sets side by side (step 5.10), as the API takes
 * them. */
export const FEWEST_COMPARED = 2
export const MOST_COMPARED = 4

/** A comparison's page (step 5.10): two to four saved runs by their keys, joined by commas, the
 * first the reference; an address the page cannot read names none. */
export const compareSearch = z.object({
  runs: z
    .string()
    .regex(/^[0-9a-f]{64}(,[0-9a-f]{64}){1,3}$/)
    .optional()
    .catch(undefined),
})

/** A saved run's results in full (step 5.22): the run by its key alone, since only a saved run
 * has results. */
export const allResultsSearch = runSearch.pick({ key: true })

type Schemas = components["schemas"]

const SIDES = [
  "long",
  "short",
] as const satisfies readonly Schemas["PositionSide"][]
/** Every role a fill can take, a trade's exit reason among them (F-TAG-01). */
export const FILL_ROLES = [
  "entry",
  "stop",
  "target_1",
  "target_2",
  "target_3",
  "exit",
  "flat_by",
  "no_overnight",
  "no_weekend",
  "max_bars",
  "max_minutes",
  "opposite_signal",
  "signal_exit",
  "roll_volume",
  "roll_open_interest",
  "roll_calendar",
  "roll_expiry",
] as const satisfies readonly Schemas["OrderRole"][]
/** The signs of a net P&L that the trade table filters by. */
export const PNL_SIGNS = [
  "positive",
  "negative",
  "zero",
] as const satisfies readonly Schemas["PnlSign"][]
/** What the trade table orders the trades by, the first the order a table opens in. */
export const TRADE_SORTS = [
  "entry_ts",
  "exit_ts",
  "pnl",
  "r_multiple",
  "held",
  "mae_ticks",
  "mfe_ticks",
] as const satisfies readonly Schemas["TradeSort"][]
const ORDERS = [
  "asc",
  "desc",
] as const satisfies readonly Schemas["SortOrder"][]
const FIDELITY = /^(trades|tbbo|[0-9]+[smhd])$/

/** A saved run's trades (step 5.8): the run by its key, the SQL tab or the table, and what the
 * table asks, its filters and its order, kept in the address as the Runs page keeps its filters,
 * so that a reload and a link keep them; a value the page cannot read is left out, a date the
 * calendar does not hold among them, and both dates where From comes after To. From step 5.9 the
 * trade the chart shows, `trade`, its row, so that a link opens the chart on it. */
export const tradesSearch = z
  .object({
    key: runSearch.shape.key,
    tab: z.literal("sql").optional().catch(undefined),
    side: z.enum(SIDES).optional().catch(undefined),
    exit_reason: z.enum(FILL_ROLES).optional().catch(undefined),
    start: z.string().refine(isTradeDate).optional().catch(undefined),
    end: z.string().refine(isTradeDate).optional().catch(undefined),
    pnl_sign: z.enum(PNL_SIGNS).optional().catch(undefined),
    fidelity: z.string().regex(FIDELITY).optional().catch(undefined),
    ambiguous: z.boolean().optional().catch(undefined),
    sort: z.enum(TRADE_SORTS).optional().catch(undefined),
    order: z.enum(ORDERS).optional().catch(undefined),
    trade: z.number().int().nonnegative().optional().catch(undefined),
  })
  .transform((search) =>
    search.start !== undefined &&
    search.end !== undefined &&
    search.start > search.end
      ? { ...search, start: undefined, end: undefined }
      : search
  )

export type TradesSearch = z.infer<typeof tradesSearch>
