import type { Page, Route } from "@playwright/test"
import { z } from "zod"

// A run's market exposure as `GET /v1/runs/{run}/market` answers it (step 5.23), and the answer
// the specs give the seeded run, whose two trade dates count none: a second seeded run would read
// the data the delete spec counts as read by none. The schemas are strict, so that an answer of
// another shape than the server's fails here before a spec compares a page with it.

const why = z.enum([
  "too_few_days",
  "market_never_differed",
  "run_never_differed",
])
const days = z.strictObject({
  days: z.number(),
  correlation: z.number().nullable(),
  beta_lots: z.number().nullable(),
  uncounted: why.nullable(),
})
/** How a run's days moved with the market's over some of them. */
export type Days = z.infer<typeof days>
const held = z.strictObject({
  lots: z.number(),
  net_pnl: z.string(),
  max_drawdown: z.string(),
  longest_drawdown_days: z.number(),
  sharpe: z.number().nullable(),
})
/** Buy and hold at one size. */
export type Held = z.infer<typeof held>
const sized = z.strictObject({
  kind: z.literal("sized"),
  at_one_lot: held,
  at_run_volatility: held,
  curve: z.strictObject({
    time: z.array(z.number()),
    equity: z.array(z.number()),
  }),
})
const unsized = z.strictObject({
  kind: z.literal("unsized"),
  at_one_lot: held,
  uncounted: why,
})
export const exposure = z.strictObject({
  all_days: days.extend({
    explained_share: z.number().nullable(),
    alpha: z.number().nullable(),
  }),
  falling_days: days,
  rising_days: days,
  buy_and_hold: z.discriminatedUnion("kind", [sized, unsized]),
})
/** A run's market exposure as the API answers it. */
export type Exposure = z.infer<typeof exposure>
const curve = z.looseObject({ capital: z.number(), time: z.array(z.number()) })

/** The figures the specs give the seeded run, as a run of nineteen trade dates counts them: the
 * explained share the correlation squared. */
export const COUNTED = {
  all_days: {
    days: 19,
    correlation: 0.4213,
    beta_lots: 0.3108,
    uncounted: null,
    explained_share: 0.17749,
    alpha: -1234.567,
  },
  falling_days: {
    days: 9,
    correlation: 0.5521,
    beta_lots: 0.4702,
    uncounted: null,
  },
  rising_days: {
    days: 10,
    correlation: -0.2104,
    beta_lots: -0.1846,
    uncounted: null,
  },
} as const
/** The lots of the given buy and hold at the run's volatility, the beta over the correlation, as
 * the server's figures relate them. */
export const SIZED_LOTS = 0.7377

/** A walk of `points` from `capital` to `capital` plus `made`, each move up to four ticks of ES
 * at $12.50 from a seeded sequence and drawn straight towards its end, so that the given curve
 * looks like a market's and is the same for every run of the spec. */
function givenWalk(capital: number, made: number, points: number): number[] {
  let state = 523
  let wandered = 0
  const sums = [0]
  for (let at = 1; at < points; at += 1) {
    // The minimal standard generator, whose products stay whole below 2^53.
    state = (state * 48_271) % 2_147_483_647
    wandered += Math.round((state / 2_147_483_647) * 8 - 4) * 12.5
    sums.push(wandered)
  }
  const last = points - 1
  return sums.map((sum, at) => {
    const drawn = last === 0 ? 0 : ((made - wandered) * at) / last
    return Math.round((capital + sum + drawn) * 100) / 100
  })
}

/** The seeded run's answer counted over `COUNTED`'s days: the server's own buy and hold at one
 * lot, and at `SIZED_LOTS` its figures as the server scales them, one lot's net P&L and drawdown
 * times the lots and its spell and Sharpe its own, with a walk at the equity's own decisions from
 * the capital to the capital plus that net P&L. */
export async function countedAnswer(
  page: Page,
  key: string
): Promise<Exposure> {
  const [own, equity] = await Promise.all([
    page.request.get(`/v1/runs/${key}/market`),
    page.request.get(`/v1/runs/${key}/equity`),
  ])
  const real = exposure.parse(await own.json())
  const { capital, time } = curve.parse(await equity.json())
  const oneLot = real.buy_and_hold.at_one_lot
  const made = Math.round(Number(oneLot.net_pnl) * SIZED_LOTS * 100) / 100
  return exposure.parse({
    ...real,
    ...COUNTED,
    buy_and_hold: {
      kind: "sized",
      at_one_lot: oneLot,
      at_run_volatility: {
        lots: SIZED_LOTS,
        net_pnl: made.toFixed(6),
        max_drawdown: (Number(oneLot.max_drawdown) * SIZED_LOTS).toFixed(6),
        longest_drawdown_days: oneLot.longest_drawdown_days,
        sharpe: oneLot.sharpe,
      },
      curve: { time, equity: givenWalk(capital, made, time.length) },
    },
  })
}

/** Answer the run's market exposure with `given` in place of the server's. */
export async function withExposure(
  page: Page,
  key: string,
  given: Exposure
): Promise<void> {
  await page.route(`**/v1/runs/${key}/market`, async (route: Route) => {
    const answered = await route.fetch()
    await route.fulfill({ response: answered, json: given })
  })
}
