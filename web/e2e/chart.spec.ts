import type { APIRequestContext, Page } from "@playwright/test"
import { z } from "zod"
import { barsPage, chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// The chart viewer of step 5.4 against the seeded server's year of MES 5-minute bars, built from
// its synthetic minutes (`scripts/e2e_server.py`): it opens from a product's row, draws hollow
// candles in the sign colours, reads the API's own bar, ends at the last bar that traded, shows
// raw prices and a contract alone, pans by the keys, leaves the wheel to a page that scrolls,
// and keeps the trader's style (Done means 1); `chart-scroll.spec.ts` scrolls back through the
// year (Done means 2). The readout's times are in the browser's zone, pinned here.

const ZONE = "America/Chicago"
test.use({ timezoneId: ZONE })

const MES = { instrument: "MES", timeframe: "5m", provider: "synthetic" }
const span = z.object({
  held: z.object({ first: z.string(), last: z.string() }),
})
const keptStyle = z.object({
  chart_style: z.object({
    up_body: z.string(),
    volume_shown: z.boolean(),
    dark: z.object({ up: z.string().nullable() }),
  }),
})

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
  return barAt(bars, bars.time.length - 1)
}

function barAt(bars: z.infer<typeof barsPage>["bars"], at: number): Bar {
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

test.afterEach(async ({ page }) => {
  // A style of no fields is FEAT's own, every field its default (`fefat_app.chart_style`).
  const me = z.object({ csrf_token: z.string() })
  const { csrf_token } = me.parse(
    await (await page.request.get("/v1/me")).json()
  )
  const reset = await page.request.put("/v1/settings", {
    data: { chart_style: {} },
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
  expect(
    await chartDraws(page, "#050505"),
    "the last price's label written in ink on its sign colour"
  ).toBe(true)
  await expect(page.getByTestId("price-chart")).toHaveAttribute(
    "data-panes",
    "2"
  )
  await screenshot(page, "data-chart")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await expect.poll(() => chartDraws(page, "#0a7a4c")).toBe(true)
  await screenshot(page, "data-chart-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  // An hour's bars show several sessions, every other one shaded, for the screenshots' readers.
  await page.goto("/data/chart?instrument=MES&provider=synthetic&timeframe=1h")
  await chartReady(page)
  await screenshot(page, "data-chart-sessions")
  expect(errors).toEqual([])
})

test("the chart ends at the last bar that traded, not at the flat rows after it", async ({
  loggedIn: page,
}) => {
  // From the builder's check of step 5.4: `load` keeps a contract that stopped trading on the
  // session grid, flat and without volume up to the session's close, and the chart opened on
  // that flat line with its candles out of view. The newest page's last bars stand for it here.
  const flat = 200
  const { held } = span.parse(
    await (
      await page.request.get("/v1/market/bars/span", { params: MES })
    ).json()
  )
  let rows = 0
  let traded: Bar | undefined
  await page.route(
    (url) => url.pathname === "/v1/market/bars",
    async (route) => {
      const response = await route.fetch()
      const answer = barsPage.loose().parse(await response.json())
      const to = new URL(route.request().url()).searchParams.get("to")
      rows += answer.bars.time.length
      if (to !== held.last || answer.next_from !== null) {
        await route.fulfill({ response, json: answer })
        return
      }
      const cut = answer.bars.time.length - flat
      traded = barAt(answer.bars, cut - 1)
      const volume = answer.bars.volume.map((each, at) => (at < cut ? each : 0))
      await route.fulfill({
        response,
        json: { ...answer, bars: { ...answer.bars, volume } },
      })
    }
  )

  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)

  if (traded === undefined) {
    throw new Error(`Expected the page of bars to ${held.last}, got none.`)
  }
  expect(traded.volume, "the bar before the flat rows traded").toBeGreaterThan(
    0
  )
  await expectReadout(page, traded)
  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "data-bars",
    String(rows - flat)
  )
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

  // Step 5.4's design review: the field took its contract on Enter alone, so one typed and left
  // showed in the field while the chart drew the spliced series.
  await expect(page.getByLabel("Contract")).toHaveAttribute(
    "placeholder",
    "Spliced"
  )
  await page.getByLabel("Contract").fill("MESH2026")
  await page.getByRole("heading", { level: 1, name: "Chart" }).click()

  await expect(page).toHaveURL(/contract=MESH2026/)
  await chartReady(page)
  await expect(page.getByRole("button", { name: "Raw" })).toHaveCount(0)
  await expectReadout(
    page,
    await lastBar(page.request, { ...MES, instrument: "MESH2026" })
  )
  await page.getByLabel("Contract").fill("MNQZ2025")
  await page.getByLabel("Contract").press("Enter")
  // The example names this year's June contract.
  const refusal = page.getByText(
    /^Type a contract of MES, such as MESM\d{4}\.$/
  )
  await expect(refusal).toBeVisible()
  const below = await refusal.boundingBox()
  const card = await page.getByTestId("chart-view").boundingBox()
  expect(
    below !== null && card !== null && below.y + below.height <= card.y,
    "the refusal clear of the chart's card"
  ).toBe(true)
  await screenshot(page, "data-chart-refusal")
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

  // At once, as Home goes: the library's own way to the newest bar slides for 400 ms, which
  // reduced motion cannot stop on a canvas (step 5.4's design review).
  await expect
    .poll(async () => Number(await view.getAttribute("data-after")), {
      timeout: 200,
    })
    .toBeLessThan(1)
})

test("the chart, reached by Tab, shows its whole focus ring inside its card", async ({
  loggedIn: page,
}) => {
  // Step 5.4's UI verification: the card clips what lies outside the chart, which fills it, so
  // the ring drawn outside the chart showed along its top edge alone.
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)
  await page.getByRole("button", { name: "Chart style" }).focus()
  await page.keyboard.press("Tab")
  const chart = page.getByTestId("price-chart")
  await expect(chart).toBeFocused()

  const ring = await chart.evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      style: style.outlineStyle,
      reach: parseFloat(style.outlineOffset) + parseFloat(style.outlineWidth),
    }
  })

  expect(ring.style).toBe("solid")
  expect(
    ring.reach,
    "the ring's outer edge, from the chart's own"
  ).toBeLessThanOrEqual(0)
})

test("a chart without a provider asks every window of the provider its span names", async ({
  loggedIn: page,
}) => {
  // Step 5.4's engine review: each window asked for the recommended provider again, so an
  // import between two windows could join one provider's bars to another's.
  const providers: (string | null)[] = []
  page.on("request", (request) => {
    const url = new URL(request.url())
    if (url.pathname === "/v1/market/bars") {
      providers.push(url.searchParams.get("provider"))
    }
  })

  await page.goto("/data/chart?instrument=ES")
  await chartReady(page)

  expect(providers.length).toBeGreaterThan(0)
  expect(new Set(providers)).toEqual(new Set(["synthetic"]))
})

test("a provider chosen gives way to the recommended one again", async ({
  loggedIn: page,
}) => {
  // Step 5.4's code review: Recommended was the empty choice's placeholder alone, so once a
  // provider was chosen nothing led back to the catalog's recommended source.
  const catalog = z
    .object({
      products: z.array(
        z.looseObject({
          datasets: z.array(z.looseObject({ root: z.string() })),
        })
      ),
    })
    .loose()
    .parse(await (await page.request.get("/v1/catalog")).json())
  const withSecond = {
    ...catalog,
    products: catalog.products.map((product) => ({
      ...product,
      datasets: product.datasets.flatMap((dataset) =>
        dataset.root === "MES"
          ? [dataset, { ...dataset, provider: "nt8" }]
          : [dataset]
      ),
    })),
  }
  await page.route("**/v1/catalog", (route) =>
    route.fulfill({ json: withSecond })
  )
  await page.goto("/data/chart?instrument=MES")
  const provider = page.getByLabel("Provider")

  await provider.click()
  await page.getByRole("option", { name: "nt8" }).click()
  await expect(page).toHaveURL(/provider=nt8/)
  await provider.click()
  await page.getByRole("option", { name: "Recommended" }).click()

  await expect(page).not.toHaveURL(/provider=/)
  await expect(provider).toHaveText("Recommended")
  await chartReady(page)
})

test("the readout keeps the bar under the pointer while older bars arrive", async ({
  loggedIn: page,
}) => {
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)
  let release: () => void = () => undefined
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(
    (url) => url.pathname === "/v1/market/bars",
    async (route) => {
      await held
      await route.continue()
    }
  )
  const chart = page.getByTestId("price-chart")
  const box = await chart.boundingBox()
  if (box === null) {
    throw new Error("Expected the chart on the page, got none.")
  }

  await chart.focus()
  await chart.press("Home")
  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "data-loading",
    "true"
  )
  // Step 5.4's design review: the chart said nothing of the window it waited for.
  await expect(page.getByTestId("chart-view")).toHaveAttribute(
    "aria-busy",
    "true"
  )
  await expect(page.getByText("Loading bars")).toBeVisible()
  const time = page.getByTestId("readout-time")
  const last = await time.textContent()
  await page.mouse.move(box.x + box.width / 3, box.y + box.height / 2)
  await expect(time).not.toHaveText(last ?? "")
  const pointed = await time.textContent()
  release()
  await chartReady(page)

  await expect(time).toHaveText(pointed ?? "")
  await expect(page.getByText("Loading bars")).toBeHidden()
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

  await page.setViewportSize({ width: 1280, height: 460 })
  const short = await chart.boundingBox()
  if (short === null) {
    throw new Error("Expected the chart on the page, got none.")
  }
  // Over the chart's own canvas, until the page knows it scrolls and leaves the wheel to it.
  await page.mouse.move(short.x + short.width / 2, short.y + 40)
  await expect
    .poll(async () => {
      await page.mouse.wheel(0, 300)
      return page.evaluate(() => window.scrollY)
    })
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

  await expect(page.getByTestId("price-chart")).toHaveAttribute(
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
  // Measured in each theme, without the theme's cross-fade, which leaves the page in the light
  // one for its screenshot.
  await page.emulateMedia({ reducedMotion: "reduce" })
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await screenshot(page, "data-chart-style-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  // The changes go to the server one after another: all three are kept before the reload.
  await expect
    .poll(
      async () =>
        keptStyle.parse(await (await page.request.get("/v1/settings")).json())
          .chart_style
    )
    .toMatchObject({
      up_body: "filled",
      volume_shown: false,
      dark: { up: "#26a69a" },
    })
  await page.reload()
  await chartReady(page)

  await expect(page.getByTestId("price-chart")).toHaveAttribute(
    "data-panes",
    "1"
  )
  await expect.poll(() => chartDraws(page, "#26a69a")).toBe(true)
  expect(errors).toEqual([])
})

test("the style drawer undoes a reset, and gives the focus back to Chart style as it closes", async ({
  loggedIn: page,
}) => {
  // Step 5.4's design review: a reset took every colour of both themes with no way back, the
  // volume's colour stayed a choice while the volume was hidden, and the focus fell to the page
  // as the drawer closed.
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)
  const opener = page.getByRole("button", { name: "Chart style" })
  await opener.click()
  await expect(opener).toHaveAttribute("aria-expanded", "true")
  const drawer = page.getByRole("dialog", { name: "Chart style" })
  const rising = drawer.getByRole("group", { name: "Rising bars" })
  const grey = drawer
    .getByRole("group", { name: "Volume colour" })
    .getByRole("button", { name: "Grey" })

  await rising.getByRole("button", { name: "Filled" }).click()
  await drawer.getByRole("button", { name: "Reset to FEAT's style" }).click()
  await expect(rising.getByRole("button", { name: "Hollow" })).toHaveAttribute(
    "aria-pressed",
    "true"
  )
  await drawer.getByRole("button", { name: "Undo reset" }).click()
  await expect(rising.getByRole("button", { name: "Filled" })).toHaveAttribute(
    "aria-pressed",
    "true"
  )
  await expect(grey).toBeEnabled()
  await drawer
    .getByRole("group", { name: "Volume" })
    .getByRole("button", { name: "Hidden" })
    .click()
  await expect(grey).toBeDisabled()
  // The drawer starts under the top bar, whose jobs indicator stays in view.
  await expect(page.getByTestId("jobs-indicator")).toBeInViewport()
  const indicator = await page.getByTestId("jobs-indicator").boundingBox()
  const panel = await page.getByTestId("chart-style-drawer").boundingBox()
  expect(
    indicator !== null &&
      panel !== null &&
      indicator.y + indicator.height <= panel.y,
    "the jobs indicator above the drawer"
  ).toBe(true)
  await page.keyboard.press("Escape")

  await expect(drawer).toBeHidden()
  await expect(opener).toBeFocused()
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
