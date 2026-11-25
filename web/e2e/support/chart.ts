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

/** The first canvas of each results chart that `testIds` name, as a picture, to compare two
 * moments of it. */
export function chartPictures(
  page: Page,
  testIds: readonly string[]
): Promise<readonly string[]> {
  return Promise.all(
    testIds.map((testId) =>
      page
        .getByTestId(testId)
        .locator("canvas")
        .first()
        .evaluate((canvas) =>
          canvas instanceof HTMLCanvasElement ? canvas.toDataURL() : ""
        )
    )
  )
}

/** Take the page to the light theme and wait until each chart that `testIds` name has repainted
 * in its tokens, which a chart does after the page takes the theme. */
export async function lightThemeDrawn(
  page: Page,
  testIds: readonly string[]
): Promise<void> {
  const dark = await chartPictures(page, testIds)
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await expect
    .poll(async () =>
      (await chartPictures(page, testIds)).some(
        (shown, at) => shown === dark[at]
      )
    )
    .toBe(false)
}
