import type { Locator, Page } from "@playwright/test"
import { barsPage, chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"

// The chart's frame of step 5.4, from the builder's third check: its right edge, its bottom
// edge, and the corner between are dragged to set the chart's size and shape, within its least
// and its column; the edges are reached by Tab after the chart and moved by the keys. At 1280
// by 800 the chart that fills is 960 px wide, its column's width. A chart taller than the
// window lengthens its page.

const CHART = "/data/chart?instrument=MES&provider=synthetic"
const LEAST = { width: 576, height: 240 }
const KEPT_AS = "fefat_chart_frame_size"
const HOW = "Drag to resize. Double-click to fill the page again."
const HOW_BY_THE_KEYS =
  "Press the arrow keys to resize. Press Enter to fill the page again."

type Box = Readonly<{ x: number; y: number; width: number; height: number }>

async function boxOf(locator: Locator): Promise<Box> {
  const box = await locator.boundingBox()
  if (box === null) {
    throw new Error("Expected the element on the page, got none.")
  }
  return box
}

/** Drag `handle` by (dx, dy) from its middle, in steps, as a pointer moves. */
async function drag(page: Page, handle: Locator, dx: number, dy: number) {
  const box = await boxOf(handle)
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + dx, y + dy, { steps: 8 })
  await page.mouse.up()
}

/** The card's width and height once they are `expected`, within a pixel. */
async function expectSize(
  card: Locator,
  expected: Readonly<{ width: number; height: number }>
) {
  await expect
    .poll(async () => {
      const box = await boxOf(card)
      return [
        Math.abs(box.width - expected.width) <= 1,
        Math.abs(box.height - expected.height) <= 1,
      ]
    })
    .toEqual([true, true])
}

function edges(page: Page) {
  return {
    card: page.getByTestId("chart-view"),
    right: page.getByRole("separator", { name: "Chart width" }),
    bottom: page.getByRole("separator", { name: "Chart height" }),
    corner: page.getByTestId("frame-corner"),
  }
}

/** How far the card's foot stands from the page's 32 px of padding over the window's foot. */
async function offItsFoot(page: Page, card: Locator): Promise<number> {
  const box = await boxOf(card)
  const windowHeight = await page.evaluate(() => window.innerHeight)
  return Math.abs(windowHeight - 32 - (box.y + box.height))
}

/** Two frames on: the page has drawn its last change, and what watches its size has heard. */
function twoFrames(page: Page): Promise<void> {
  return page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
      })
  )
}

/** What the browser keeps of the frame's size, as its text. */
function kept(page: Page): Promise<string | null> {
  return page.evaluate((key) => localStorage.getItem(key), KEPT_AS)
}

/** The outline of `edge` itself, then of its line over the card's hairline. */
function focusOutlines(edge: Locator): Promise<readonly string[]> {
  return edge.evaluate((element) => [
    getComputedStyle(element).outlineStyle,
    getComputedStyle(element, "::after").outlineStyle,
    getComputedStyle(element, "::after").outlineWidth,
  ])
}

/** How long a change of `edge`, of its line, and of the frame it sizes takes to show. */
function transitions(edge: Locator): Promise<readonly string[]> {
  return edge.evaluate((element) => [
    getComputedStyle(element).transitionDuration,
    getComputedStyle(element, "::after").transitionDuration,
    element.parentElement === null
      ? "no frame"
      : getComputedStyle(element.parentElement).transitionDuration,
  ])
}

test("dragging the right edge, the bottom edge, and the corner sizes the chart, which follows", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  await page.goto(CHART)
  await chartReady(page)
  const { card, right, bottom, corner } = edges(page)
  const filling = await boxOf(card)
  const width = Math.floor(filling.width)
  const height = Math.floor(filling.height)

  await drag(page, right, -200, 0)
  await expectSize(card, { width: width - 200, height: filling.height })
  // A press of the pointer leaves the keys where they were: End and Home, the chart's own
  // keys, size nothing after it.
  await page.keyboard.press("End")
  await page.keyboard.press("Home")
  await twoFrames(page)
  await expectSize(card, { width: width - 200, height: filling.height })
  await drag(page, bottom, 0, -80)
  await expectSize(card, { width: width - 200, height: height - 80 })
  await drag(page, corner, -40, 40)
  await expectSize(card, { width: width - 240, height: height - 40 })
  // The chart stays where its page put it: its top left corner never moves.
  const sized = await boxOf(card)
  expect(Math.abs(sized.x - filling.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(sized.y - filling.y)).toBeLessThanOrEqual(1)

  // The chart redraws to its frame: the library's own table fills the chart's box.
  const chart = await boxOf(page.getByTestId("price-chart"))
  const drawn = await boxOf(page.getByTestId("price-chart").locator("table"))
  expect(Math.abs(drawn.width - chart.width)).toBeLessThanOrEqual(2)
  expect(Math.abs(drawn.height - chart.height)).toBeLessThanOrEqual(2)
  await expect(card).toHaveAttribute("data-loading", "false")
  // The pointer off the frame, so that no edge is drawn under it.
  await page.mouse.move(700, 36)
  await screenshot(page, "data-chart-sized")
  // The pointer on the right edge, whose line lies over the card's hairline.
  const edge = await boxOf(right)
  await page.mouse.move(edge.x + 1, edge.y + edge.height / 2)
  await screenshot(page, "data-chart-edge-hover")

  // A double click on an edge gives its direction back to the page; the corner gives both.
  await right.dblclick()
  await expectSize(card, { width: filling.width, height: height - 40 })
  await bottom.dblclick()
  await expectSize(card, filling)
  await drag(page, corner, -100, -100)
  await expectSize(card, { width: width - 100, height: height - 100 })
  await corner.dblclick()
  await expectSize(card, filling)
  expect(errors).toEqual([])
})

test("a press on the card's own hairline drags the frame, the edge a pointer aims at", async ({
  loggedIn: page,
}) => {
  await page.goto(CHART)
  await chartReady(page)
  const { card } = edges(page)
  const filling = await boxOf(card)
  const width = Math.floor(filling.width)
  const height = Math.floor(filling.height)
  /** Press at (x, y) and move by (dx, dy), as a pointer that grabbed the card's edge. */
  const pull = async (x: number, y: number, dx: number, dy: number) => {
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x + dx, y + dy, { steps: 8 })
    await page.mouse.up()
  }

  // The card's last whole pixel at its right and at its foot, where the chart's axes end: a
  // press there sizes the frame, rather than scale the chart's prices or its time.
  await pull(
    Math.ceil(filling.x + filling.width) - 1,
    Math.round(filling.y + filling.height / 2),
    -200,
    0
  )
  await expectSize(card, { width: width - 200, height: filling.height })
  const narrow = await boxOf(card)
  await pull(
    Math.round(narrow.x + narrow.width / 2),
    Math.ceil(narrow.y + narrow.height) - 1,
    0,
    -80
  )
  await expectSize(card, { width: width - 200, height: height - 80 })

  // The corner says how it is used, and reaches as far outside the card as the edges do.
  await expect(edges(page).corner).toHaveAttribute("title", HOW)
  const small = await boxOf(card)
  await pull(
    Math.ceil(small.x + small.width) + 3,
    Math.ceil(small.y + small.height) + 3,
    40,
    40
  )
  await expectSize(card, { width: width - 160, height: height - 40 })
})

test("the chart keeps its least size, never passes its column, and narrows beside the style drawer", async ({
  loggedIn: page,
}) => {
  await page.goto(CHART)
  await chartReady(page)
  const { card, right, bottom } = edges(page)
  const filling = await boxOf(card)
  const sideways = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth
    )

  await drag(page, right, -700, 0)
  await expectSize(card, { width: LEAST.width, height: filling.height })
  await drag(page, bottom, 0, -400)
  await expectSize(card, LEAST)
  // Back past its column, the width is the column's again, and nothing scrolls sideways.
  await drag(page, right, 400, 0)
  await expectSize(card, { width: filling.width, height: LEAST.height })
  expect(await sideways()).toBeLessThanOrEqual(0)
  // A set width narrows while the drawer takes its room, and comes back with it.
  await drag(page, right, -200, 0)
  const set = Math.floor(filling.width) - 200
  await expectSize(card, { width: set, height: LEAST.height })
  await page.getByRole("button", { name: "Chart style" }).click()
  await expect(page.getByRole("dialog", { name: "Chart style" })).toBeVisible()
  await expectSize(card, { width: filling.width - 384, height: LEAST.height })
  expect(await sideways()).toBeLessThanOrEqual(0)
  await page.keyboard.press("Escape")
  await expectSize(card, { width: set, height: LEAST.height })
})

test("at the chart's least width the readout cuts no figure of an index future's prices", async ({
  loggedIn: page,
}) => {
  // MNQ's figures, five digits with two decimals and a volume in the tens of thousands, which
  // the seed has none of: MES's bars as the API sends them, 20,000 points higher and a hundred
  // times the volume.
  await page.route(
    (url) => url.pathname === "/v1/market/bars",
    async (route) => {
      const response = await route.fetch()
      const answer = barsPage.loose().parse(await response.json())
      const higher = (prices: readonly number[]) =>
        prices.map((price) => price + 20_000)
      const { open, high, low, close, volume } = answer.bars
      await route.fulfill({
        response,
        json: {
          ...answer,
          bars: {
            ...answer.bars,
            open: higher(open),
            high: higher(high),
            low: higher(low),
            close: higher(close),
            volume: volume.map((lots) => lots * 100),
          },
        },
      })
    }
  )
  await page.goto(CHART)
  await chartReady(page)
  const { card, right } = edges(page)
  await expect(page.getByTestId("readout-volume")).toHaveText(/^\d\d,\d{3}$/)

  const filling = await boxOf(card)
  await drag(page, right, -700, 0)
  await expectSize(card, { width: LEAST.width, height: filling.height })

  // Each figure ends inside the card's padding, 16 px from its edge.
  const inside = await boxOf(card)
  for (const figure of ["open", "high", "low", "close", "volume"]) {
    const box = await boxOf(page.getByTestId(`readout-${figure}`))
    expect(box.x + box.width, `the readout's ${figure}`).toBeLessThanOrEqual(
      inside.x + inside.width - 16
    )
  }
  await page.mouse.move(700, 36)
  await screenshot(page, "data-chart-least")
})

test("the chart's size outlives a change of timeframe and a reload, kept in this browser", async ({
  loggedIn: page,
}) => {
  await page.goto(CHART)
  await chartReady(page)
  const { card, right, bottom } = edges(page)
  const filling = await boxOf(card)
  const set = {
    width: Math.floor(filling.width) - 200,
    height: Math.floor(filling.height) - 80,
  }
  expect(await kept(page), "nothing kept before an edge is dragged").toBeNull()

  await drag(page, right, -200, 0)
  await drag(page, bottom, 0, -80)
  await expectSize(card, set)
  // Another timeframe is another chart, drawn in the frame as the trader left it.
  await page.getByLabel("Timeframe").click()
  await page.getByRole("option", { name: "1h" }).click()
  await expect(page).toHaveURL(/timeframe=1h/)
  await expect(
    page.getByRole("application", { name: "MES, 1-hour bars" })
  ).toBeVisible()
  await chartReady(page)
  await expectSize(card, set)
  expect(await kept(page)).toBe(JSON.stringify(set))
  await page.reload()
  await chartReady(page)
  await expectSize(card, set)

  // What the browser keeps is the trader's to edit: a text that is no size fills the page,
  // and a height past the frame's most is drawn at the most, 1600 px in this window.
  const keep = (text: string) =>
    page.evaluate(
      ([key, value]) => localStorage.setItem(key, value),
      [KEPT_AS, text]
    )
  await keep("{broken")
  await page.reload()
  await chartReady(page)
  await expectSize(card, filling)
  await keep('{"width":null,"height":5000}')
  await page.reload()
  await chartReady(page)
  await expectSize(card, { width: filling.width, height: 1600 })
})

test("in a window taller than 1600 px a chart that fills is within its most, and a pull grows it", async ({
  loggedIn: page,
}) => {
  await page.setViewportSize({ width: 1280, height: 2000 })
  await page.goto(CHART)
  await chartReady(page)
  const { card, bottom } = edges(page)
  const filling = await boxOf(card)
  expect(filling.height, "the chart that fills this window").toBeGreaterThan(
    1600
  )
  // The most is the window's height where that is over 1600 px.
  await expect(bottom).toHaveAttribute("aria-valuemax", "2000")

  await drag(page, bottom, 0, 20)

  const set = Math.floor(filling.height) + 20
  await expectSize(card, { width: filling.width, height: set })
  // A height over 1600 px is kept as any other.
  await page.reload()
  await chartReady(page)
  await expectSize(card, { width: filling.width, height: set })
})

test("a width dragged to its column fills it, in a window made narrower during the drag", async ({
  loggedIn: page,
}) => {
  await page.goto(CHART)
  await chartReady(page)
  const { card, right } = edges(page)
  const filling = await boxOf(card)
  const widthIs = (expected: number) =>
    expect
      .poll(async () => Math.abs((await boxOf(card)).width - expected))
      .toBeLessThanOrEqual(1)
  await drag(page, right, -260, 0)
  await widthIs(Math.floor(filling.width) - 260)

  // The press, then a narrower window, as when the page's scrollbar arrives under a chart
  // made taller: the column is 780 px, and the pointer ends 4 px short of it.
  const edge = await boxOf(right)
  const x = edge.x + edge.width / 2
  const y = edge.y + edge.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 5, y)
  await page.setViewportSize({ width: 1100, height: 800 })
  await page.mouse.move(x + 76, y, { steps: 4 })
  await page.mouse.up()
  await widthIs(780)

  // In its own window again the chart fills its column, where a width kept at 776 px stays.
  await page.setViewportSize({ width: 1280, height: 800 })
  await widthIs(filling.width)
})

test("a chart that fills keeps its least height over a failure in a short window", async ({
  loggedIn: page,
}) => {
  // The page's least height leaves the chart some 300 px, and a failure under it takes 90.
  await page.setViewportSize({ width: 1280, height: 460 })
  await page.route(
    (url) => url.pathname === "/v1/market/bars",
    (route) =>
      route.fulfill(
        problemAnswer(500, "The server failed on purpose, for this test.")
      )
  )
  await page.goto(CHART)
  const { card, bottom } = edges(page)
  await expect(page.getByRole("main").getByRole("alert")).toHaveText(
    "The server failed on purpose, for this test."
  )

  expect((await boxOf(card)).height).toBeGreaterThanOrEqual(LEAST.height)
  await expect(bottom).toHaveAttribute("aria-valuenow", String(LEAST.height))
})

test("the edges follow the chart in the Tab order, say their size, and move by the keys", async ({
  loggedIn: page,
}) => {
  await page.goto(CHART)
  await chartReady(page)
  const { card, right, bottom } = edges(page)
  const filling = await boxOf(card)
  const width = Math.floor(filling.width)
  const height = Math.floor(filling.height)

  // After the chart and the library's logo, a link inside it.
  await page.getByRole("button", { name: "Chart style" }).focus()
  await page.keyboard.press("Tab")
  await expect(page.getByTestId("price-chart")).toBeFocused()
  await page.keyboard.press("Tab")
  await page.keyboard.press("Tab")
  await expect(right).toBeFocused()
  await expect(right).toHaveAttribute("aria-orientation", "vertical")
  await expect(right).toHaveAttribute("aria-valuenow", String(width))
  await expect(right).toHaveAttribute("aria-valuemin", String(LEAST.width))
  await expect(right).toHaveAttribute("aria-valuemax", String(width))
  // Its tooltip is the pointer's, which a press leaves without the keys; who Tabs here hears
  // the keys' sentence.
  await expect(right).toHaveAttribute("title", HOW)
  await expect(right).toHaveAccessibleDescription(HOW_BY_THE_KEYS)
  // The focus shows on the line the trader sees, not around the strip a pointer grabs.
  expect(await focusOutlines(right)).toEqual(["none", "solid", "2px"])
  // A frame follows the hand at once: neither its size nor its edge's line is eased.
  expect(await transitions(right)).toEqual(["0s", "0s", "0s"])
  await screenshot(page, "data-chart-edge-focused")

  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  await expectSize(card, { width: width - 32, height: filling.height })
  await expect(right).toHaveAttribute("aria-valuenow", String(width - 32))
  await expect(right).toHaveAttribute("aria-valuetext", `${width - 32} pixels`)
  await page.keyboard.press("Home")
  await expectSize(card, { width: LEAST.width, height: filling.height })
  await page.keyboard.press("End")
  await expectSize(card, filling)
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("Enter")
  await expectSize(card, filling)

  await page.keyboard.press("Tab")
  await expect(bottom).toBeFocused()
  await expect(bottom).toHaveAttribute("aria-orientation", "horizontal")
  await expect(bottom).toHaveAttribute("aria-valuenow", String(height))
  await expect(bottom).toHaveAttribute("aria-valuemin", String(LEAST.height))
  await expect(bottom).toHaveAttribute("aria-valuemax", "1600")
  await expect(bottom).toHaveAttribute("title", HOW)
  await expect(bottom).toHaveAccessibleDescription(HOW_BY_THE_KEYS)
  expect(await focusOutlines(bottom)).toEqual(["none", "solid", "2px"])
  expect(await transitions(bottom)).toEqual(["0s", "0s", "0s"])
  await screenshot(page, "data-chart-edge-focused-bottom")
  await page.keyboard.press("ArrowUp")
  await expectSize(card, { width: filling.width, height: height - 16 })
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("ArrowDown")
  await expectSize(card, { width: filling.width, height: height + 16 })
  await page.keyboard.press("Home")
  await expectSize(card, { width: filling.width, height: LEAST.height })
  await page.keyboard.press("Enter")
  await expectSize(card, filling)
})

test("a corner pulled sideways sets the width alone, a height that fills left to fill", async ({
  loggedIn: page,
}) => {
  await page.goto(CHART)
  await chartReady(page)
  const { card, corner } = edges(page)
  const filling = await boxOf(card)
  const width = Math.floor(filling.width)

  // A hand that pulls the corner left wanders a few pixels down.
  await drag(page, corner, -200, 5)

  await expectSize(card, { width: width - 200, height: filling.height })
  expect(await kept(page)).toBe(
    JSON.stringify({ width: width - 200, height: null })
  )
})

test("a chart set taller than the window lengthens its page, which the wheel then scrolls", async ({
  loggedIn: page,
}) => {
  await page.goto(CHART)
  await chartReady(page)
  const { card, bottom } = edges(page)
  const filling = await boxOf(card)
  expect(Math.abs(filling.width - 960)).toBeLessThanOrEqual(1)

  // A chart that fills ends at the page's padding, in a window made shorter and taller again,
  // and its page is never longer than the window.
  for (const height of [800, 700, 800]) {
    await page.setViewportSize({ width: 1280, height })
    await expect
      .poll(() => offItsFoot(page, card), {
        message: `the chart that fills, in a window ${height} px high`,
      })
      .toBeLessThanOrEqual(1)
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollHeight -
          document.documentElement.clientHeight
      )
    ).toBe(0)
  }

  await bottom.focus()
  await page.keyboard.press("End")
  await expectSize(card, { width: filling.width, height: 1600 })
  // The edge the keys hold stays in view as its frame grows past the window's foot.
  await expect(bottom).toBeInViewport()
  // The page is as long as its chart: at its end, its padding stands under the card.
  await page.evaluate(() =>
    window.scrollTo(0, document.documentElement.scrollHeight)
  )
  await expect
    .poll(() => offItsFoot(page, card), {
      message: "the page's padding under a chart taller than the window",
    })
    .toBeLessThanOrEqual(1)

  // The wheel belongs to a page that scrolls, as in a window too short for the chart.
  await page.evaluate(() => window.scrollTo(0, 0))
  await twoFrames(page)
  const before = await card.getAttribute("data-before")
  await page.mouse.move(filling.x + filling.width / 2, filling.y + 120)
  await expect
    .poll(async () => {
      await page.mouse.wheel(0, 300)
      return page.evaluate(() => window.scrollY)
    })
    .toBeGreaterThan(0)
  await twoFrames(page)
  await expect(card).toHaveAttribute("data-before", String(before))
})
