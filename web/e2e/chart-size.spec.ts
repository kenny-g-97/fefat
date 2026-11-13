import type { Locator, Page } from "@playwright/test"
import { chartReady } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// The chart's frame of step 5.4, from the builder's third check: its right edge, its bottom
// edge, and the corner between are dragged to set the chart's size and shape, within its least
// and its column; the edges are reached by Tab after the chart and moved by the keys. At 1280
// by 800 the chart that fills is 960 px wide, its column's width.

const CHART = "/data/chart?instrument=MES&provider=synthetic"
const LEAST = { width: 576, height: 240 }
const HOW =
  "Drag or press the arrow keys to resize. Double-click or press Enter to fill the page again."

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
  await drag(page, bottom, 0, -80)
  await expectSize(card, { width: width - 200, height: height - 80 })
  await drag(page, corner, -40, 40)
  await expectSize(card, { width: width - 240, height: height - 40 })

  // The chart redraws to its frame: the library's own table fills the chart's box.
  const chart = await boxOf(page.getByTestId("price-chart"))
  const drawn = await boxOf(page.getByTestId("price-chart").locator("table"))
  expect(Math.abs(drawn.width - chart.width)).toBeLessThanOrEqual(2)
  expect(Math.abs(drawn.height - chart.height)).toBeLessThanOrEqual(2)
  await expect(card).toHaveAttribute("data-loading", "false")
  // The pointer off the frame, so that no edge is drawn under it.
  await page.mouse.move(700, 36)
  await screenshot(page, "data-chart-sized")

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
  const kept = () =>
    page.evaluate(() => localStorage.getItem("fefat_chart_frame_size"))
  expect(await kept(), "nothing kept before an edge is dragged").toBeNull()

  await drag(page, right, -200, 0)
  await drag(page, bottom, 0, -80)
  await expectSize(card, set)
  // Another timeframe is another chart, drawn in the frame as the trader left it.
  await page.getByLabel("Timeframe").click()
  await page.getByRole("option", { name: "1h" }).click()
  await expect(page).toHaveURL(/timeframe=1h/)
  await chartReady(page)
  await expectSize(card, set)
  expect(await kept()).toBe(JSON.stringify(set))
  await page.reload()
  await chartReady(page)
  await expectSize(card, set)

  // What the browser keeps is the trader's to edit: a text that is no size fills the page.
  await page.evaluate(() =>
    localStorage.setItem("fefat_chart_frame_size", "{broken")
  )
  await page.reload()
  await chartReady(page)
  await expectSize(card, filling)
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
  await expect(right).toHaveAttribute("title", HOW)

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
