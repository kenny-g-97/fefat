import type { APIRequestContext, Page } from "@playwright/test"
import { z } from "zod"
import { barsPage, chartReady } from "./support/chart.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// The chart viewer of step 5.4 against the seeded server's year of MES 5-minute bars, built from
// its synthetic minutes (`scripts/e2e_server.py`): it opens from a product's row, draws hollow
// candles in the sign colours, reads the API's own bar, shows raw prices and a contract alone,
// pans by the keys, leaves the wheel to a page that scrolls, and keeps the trader's style
// (Done means 1); `chart-scroll.spec.ts` scrolls back through the year (Done means 2). The
// readout's times are in the browser's zone, pinned here.

const ZONE = "America/Chicago"
test.use({ timezoneId: ZONE })

const MES = { instrument: "MES", timeframe: "5m", provider: "synthetic" }
const span = z.object({
  held: z.object({ first: z.string(), last: z.string() }),
})
const THEMES_OWN = {
  up: null,
  down: null,
  background: null,
  grid: null,
  text: null,
}
const FEATS_STYLE = {
  up_body: "hollow",
  down_body: "hollow",
  volume_shown: true,
  volume_colouring: "neutral",
  grid_shown: true,
  sessions_shaded: true,
  dark: THEMES_OWN,
  light: THEMES_OWN,
}

type Bar = Readonly<{
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  contract: string
}>

/** The last bar the API gives of a series, read page by page over its last trade date. */
async function lastBar(
  request: APIRequestContext,
  query: Readonly<Record<string, string>>
): Promise<Bar> {
  const held = span.parse(
    await (await request.get("/v1/market/bars/span", { params: query })).json()
  ).held
  let from: string | null = held.last
  let bars: z.infer<typeof barsPage>["bars"] | undefined
  while (from !== null) {
    const answer = barsPage.parse(
      await (
        await request.get("/v1/market/bars", {
          params: { ...query, from, to: held.last },
        })
      ).json()
    )
    bars = answer.bars.time.length > 0 ? answer.bars : bars
    from = answer.next_from
  }
  if (bars === undefined) {
    throw new Error(`Expected bars of ${JSON.stringify(query)}, got none.`)
  }
  const at = bars.time.length - 1
  return {
    time: bars.time[at],
    open: bars.open[at],
    high: bars.high[at],
    low: bars.low[at],
    close: bars.close[at],
    volume: bars.volume[at],
    contract: bars.contract[at],
  }
}

/** An open as the readout shows it, in the pinned zone. */
function inTheZone(seconds: number): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(seconds * 1000))
  const part = (type: string) => parts.find((each) => each.type === type)?.value
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")}`
}

async function expectReadout(page: Page, bar: Bar): Promise<void> {
  await expect(page.getByTestId("readout-contract")).toHaveText(bar.contract)
  await expect(page.getByTestId("readout-time")).toHaveText(inTheZone(bar.time))
  await expect(page.getByTestId("readout-open")).toHaveText(bar.open.toFixed(2))
  await expect(page.getByTestId("readout-high")).toHaveText(bar.high.toFixed(2))
  await expect(page.getByTestId("readout-low")).toHaveText(bar.low.toFixed(2))
  await expect(page.getByTestId("readout-close")).toHaveText(
    bar.close.toFixed(2)
  )
  await expect(page.getByTestId("readout-volume")).toHaveText(
    bar.volume.toLocaleString("en-US")
  )
}

/** Whether a canvas of the chart holds a pixel of `hex`, as a candle's border draws it. */
function chartDraws(page: Page, hex: string): Promise<boolean> {
  return page.getByTestId("price-chart").evaluate((frame, wanted) => {
    const channels = [1, 3, 5].map((at) =>
      parseInt(wanted.slice(at, at + 2), 16)
    )
    return [...frame.querySelectorAll("canvas")].some((canvas) => {
      const context = canvas.getContext("2d")
      if (context === null || canvas.width === 0 || canvas.height === 0) {
        return false
      }
      const pixels = context.getImageData(
        0,
        0,
        canvas.width,
        canvas.height
      ).data
      for (let at = 0; at < pixels.length; at += 4) {
        const near = channels.every(
          (channel, index) => Math.abs(pixels[at + index] - channel) <= 2
        )
        if (near && pixels[at + 3] === 255) {
          return true
        }
      }
      return false
    })
  }, hex)
}

function consoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text())
    }
  })
  page.on("pageerror", (error) => errors.push(error.message))
  return errors
}

test.afterEach(async ({ page }) => {
  const me = z.object({ csrf_token: z.string() })
  const { csrf_token } = me.parse(
    await (await page.request.get("/v1/me")).json()
  )
  const reset = await page.request.put("/v1/settings", {
    data: { chart_style: FEATS_STYLE },
    headers: { "X-CSRF-Token": csrf_token },
  })
  expect(reset.status()).toBe(200)
})

test("a product's Chart opens its bars in the sign colours, its readout the API's last bar", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/data")
  await page
    .getByRole("region", { name: "Catalog products" })
    .getByRole("link", { name: "Chart" })
    .first()
    .click()

  await expect(page).toHaveURL(
    "/data/chart?instrument=MES&provider=synthetic&timeframe=5m&prices=adjusted"
  )
  await expect(page).toHaveTitle("Chart – FEAT")
  await chartReady(page)

  await expectReadout(page, await lastBar(page.request, MES))
  expect(
    await chartDraws(page, "#10b981"),
    "rising candles in the positive colour"
  ).toBe(true)
  expect(
    await chartDraws(page, "#ff4d6d"),
    "falling candles in the negative colour"
  ).toBe(true)
  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "data-panes",
    "2"
  )
  await screenshot(page, "data-chart")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await expect.poll(() => chartDraws(page, "#0a7a4c")).toBe(true)
  await screenshot(page, "data-chart-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("Raw shows the spliced series at the prices its contracts traded at", async ({
  loggedIn: page,
}) => {
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)

  await page.getByRole("button", { name: "Raw" }).click()

  await expect(page).toHaveURL(/prices=raw/)
  await chartReady(page)
  const raw = await lastBar(page.request, { ...MES, prices: "raw" })
  const adjusted = await lastBar(page.request, MES)
  expect(raw.close).not.toBe(adjusted.close)
  await expectReadout(page, raw)
})

test("a contract typed in its field is charted alone", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)

  await page.getByLabel("Contract").fill("MESH2026")
  await page.getByLabel("Contract").press("Enter")

  await expect(page).toHaveURL(/contract=MESH2026/)
  await chartReady(page)
  await expect(page.getByRole("button", { name: "Raw" })).toHaveCount(0)
  await expectReadout(
    page,
    await lastBar(page.request, { ...MES, instrument: "MESH2026" })
  )
  await page.getByLabel("Contract").fill("MNQZ2025")
  await page.getByLabel("Contract").press("Enter")
  await expect(
    page.getByText("Type a contract of MES, such as MESM2026.")
  ).toBeVisible()
  expect(errors).toEqual([])
})

test("the keys pan the focused chart to either end of what it loaded", async ({
  loggedIn: page,
}) => {
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)
  const view = page.getByTestId("chart-view")
  const chart = page.getByTestId("price-chart")

  await chart.focus()
  await chart.press("ArrowLeft")
  await expect
    .poll(async () => Number(await view.getAttribute("data-after")))
    .toBeGreaterThan(5)
  await chart.press("End")

  await expect
    .poll(async () => Number(await view.getAttribute("data-after")))
    .toBeLessThan(1)
})

test("the wheel zooms the chart, and scrolls a page too short for the chart", async ({
  loggedIn: page,
}) => {
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)
  const chart = page.getByTestId("price-chart")
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the chart on the page, got none.")
  }
  const before = await page
    .getByTestId("chart-view")
    .getAttribute("data-before")

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -400)

  await expect(page.getByTestId("chart-view")).not.toHaveAttribute(
    "data-before",
    String(before)
  )
  expect(await page.evaluate(() => window.scrollY)).toBe(0)

  await page.setViewportSize({ width: 1280, height: 460 })
  await page.mouse.move(box.x + box.width / 2, 300)
  await page.mouse.wheel(0, 300)
  await expect
    .poll(() => page.evaluate(() => window.scrollY))
    .toBeGreaterThan(0)
})

test("the chart's style changes as it is chosen and stays chosen", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)

  await page.getByRole("button", { name: "Chart style" }).click()
  const drawer = page.getByRole("dialog", { name: "Chart style" })
  await drawer
    .getByRole("group", { name: "Rising bars" })
    .getByRole("button", { name: "Filled" })
    .click()
  await drawer.getByLabel("Rising", { exact: true }).fill("#26a69a")
  await drawer
    .getByRole("group", { name: "Volume" })
    .getByRole("button", { name: "Hidden" })
    .click()

  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "data-panes",
    "1"
  )
  await expect.poll(() => chartDraws(page, "#26a69a")).toBe(true)
  await expect(drawer).toBeVisible()
  expect(
    await page
      .getByTestId("chart-style-settings")
      .evaluate((settings) => settings.scrollHeight <= settings.clientHeight),
    "every setting in view at 1280 by 800"
  ).toBe(true)
  await screenshot(page, "data-chart-style")
  await page.reload()
  await chartReady(page)
  const kept = z
    .object({
      chart_style: z.object({
        up_body: z.string(),
        volume_shown: z.boolean(),
        dark: z.object({ up: z.string().nullable() }),
      }),
    })
    .parse(await (await page.request.get("/v1/settings")).json())
  expect(kept.chart_style).toMatchObject({
    up_body: "filled",
    volume_shown: false,
    dark: { up: "#26a69a" },
  })
  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "data-panes",
    "1"
  )
  expect(errors).toEqual([])
})

test("a series the store cannot give says why in the SDK's words", async ({
  loggedIn: page,
}) => {
  await page.goto("/data/chart?instrument=ES&provider=nobody")

  await expect(page.getByRole("alert")).toContainText(
    "Expected a provider of ES in the store (synthetic), got 'nobody'."
  )
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible()
})
