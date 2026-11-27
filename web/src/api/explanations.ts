import { useMutation } from "@tanstack/react-query"
import { z } from "zod"
import { api, queryClient } from "./client"
import { jobsQuery } from "./jobs"
import { answer } from "./problems"

/** What the reference engine's log says happened (`fefat.reference.event_log.EventKind`). */
const EVENT_KINDS = [
  "placed",
  "active",
  "triggered",
  "filled",
  "cancelled",
  "funding",
  "break",
  "ambiguous",
  "moved",
  "reduced",
  "skipped",
  "rolled",
  "warning",
] as const

const explainedEvent = z.object({
  time: z.string(),
  kind: z.enum(EVENT_KINDS),
  order: z.number().nullable(),
  rule: z.string().nullable(),
  text: z.string(),
})

const explainedFill = z.object({
  order: z.number(),
  role: z.string(),
  side: z.enum(["buy", "sell"]),
  lots: z.number(),
  time: z.string(),
  price: z.string(),
  rule: z.string(),
  liquidity: z.enum(["maker", "taker"]),
  slippage_ticks: z.number(),
  fee: z.string(),
  flags: z.array(z.enum(["ambiguous", "size_exceeded"])),
  fidelity: z.string(),
  contract: z.string(),
})

/** An `explain` job's result, which the OpenAPI document does not type
 * (`fefat_app.jobs.trade_explanations`, step 5.9): the trade replayed through the reference
 * engine, its heading, the instant its replay's first record starts at, its log's events in the
 * order they happened, and its fills; or why the replay refused it, in words. */
export const tradeExplanation = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("explained"),
    trade_id: z.number(),
    heading: z.string(),
    started_at: z.string(),
    events: z.array(explainedEvent),
    fills: z.array(explainedFill),
  }),
  z.object({
    kind: z.literal("refused"),
    trade_id: z.number(),
    reason: z.string(),
  }),
])

export type TradeExplanation = z.infer<typeof tradeExplanation>
/** An event of a replay's log. */
export type ExplainedEvent = z.infer<typeof explainedEvent>

/** Queue the explanation of a trade of the saved run `runKey` by its id, its entry order, as an
 * `explain` job, which the jobs drawer follows; the job of the same trade already under way
 * where there is one. */
export function useExplainStart(runKey: string) {
  return useMutation({
    mutationFn: async (tradeId: number) =>
      answer(
        await api.POST("/v1/runs/{run}/explain/{trade_id}", {
          params: { path: { run: runKey, trade_id: tradeId } },
        })
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  })
}
