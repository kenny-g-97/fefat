import { expect, type Page } from "@playwright/test"
import { z } from "zod"

/** A page of `GET /v1/market/bars` as the specs read it. */
export const barsPage = z.object({
  bars: z.object({
    time: z.array(z.number()),
    trade_date: z.array(z.string()),
    open: z.array(z.number()),
    high: z.array(z.number()),
    low: z.array(z.number()),
    close: z.array(z.number()),
    volume: z.array(z.number()),
    contract: z.array(z.string()),
  }),
  next_from: z.string().nullable(),
})

/** Wait until the chart has drawn every window it asked for, its view's `data-loading` false. */
export async function chartReady(page: Page): Promise<void> {
  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "data-loading",
    "false",
    {
      timeout: 30_000,
    }
  )
}
