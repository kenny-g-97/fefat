import { barsPage, chartReady } from "./support/chart.ts"
import { expect, test } from "./support/fixtures.ts"

// Done means 2 of step 5.4: scrolling back on a year of 5-minute bars stays smooth, no request
// larger than 20,000 bars, and requests cached. The seed's year of MES, 2025-04-01 to 2026-03-31,
// comes in 14 windows of 27 days, each asked once, a window at a time as the view nears the
// oldest bar, back to the first bar the API sends (its first session has no front, so it is the
// second's); a chart drawn again, as Raw and back to Adjusted draw it, reads its windows from the
// cache. The clip of it is the builder's check (`docs/validation/screenshots/5.4/`).

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

test("a year of 5-minute bars loads a window at a time, each request at most 20,000 bars and none asked twice", async ({
  loggedIn: page,
}) => {
  const asked: string[] = []
  const sizes: number[] = []
  const firstDates: string[] = []
  page.on("request", (request) => {
    const url = new URL(request.url())
    if (url.pathname === "/v1/market/bars") {
      const query = url.searchParams
      asked.push(
        `${query.get("prices")} ${query.get("from")} ${query.get("to")}`
      )
    }
  })
  page.on("response", async (response) => {
    if (new URL(response.url()).pathname !== "/v1/market/bars") {
      return
    }
    const answer = barsPage.parse(await response.json())
    sizes.push(answer.bars.time.length)
    firstDates.push(...answer.bars.trade_date.slice(0, 1))
  })
  await page.goto("/data/chart?instrument=MES&provider=synthetic")
  await chartReady(page)
  const view = page.getByTestId("chart-view")
  const chart = page.getByTestId("price-chart")
  // The newest window alone, until the view nears its oldest bar.
  await expect(view).toHaveAttribute("data-windows", "1 of 14")
  await chart.focus()

  for (let back = 0; back < 20; back += 1) {
    const windows = await view.getAttribute("data-windows")
    const before = Number(await view.getAttribute("data-before"))
    if (windows === "14 of 14" && before < 1) {
      break
    }
    await chart.press("Home")
    await page.waitForTimeout(300)
    await chartReady(page)
  }

  const first = firstDates.toSorted().at(0)
  if (first === undefined) {
    throw new Error("Expected bars of MES from the API, got none.")
  }
  await expect(view).toHaveAttribute("data-windows", "14 of 14")
  await expect(view).toHaveAttribute("data-first-date", first)
  expect(Math.max(...sizes)).toBeLessThanOrEqual(20_000)
  expect(new Set(asked).size).toBe(asked.length)

  for (const prices of ["Raw", "Adjusted"]) {
    const choice = page.getByRole("button", { name: prices })
    await choice.click()
    await expect(choice).toHaveAttribute("aria-pressed", "true")
    await chartReady(page)
  }
  expect(asked.some((each) => each.startsWith("raw "))).toBe(true)
  expect(new Set(asked).size).toBe(asked.length)
})
