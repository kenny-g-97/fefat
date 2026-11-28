import { z } from "zod"
import { lightThemeDrawn } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { moneyText } from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededRuns } from "./support/seeded-run.ts"

// The comparison of step 5.10 (D-126) against the seeded server: the two saved runs of demo, its
// version 1 and version 2's wider stop, ticked on the Runs page, open their comparison, the older
// the reference, whose figures and changes are the API's, read here with the spec's own
// formatting (Done means 1 for the comparison; its deltas are the stored metrics' differences in
// python/tests/server/test_http_runs_compare.py).

test.use({ timezoneId: "UTC" })

const figures = z.looseObject({ pnl: z.string(), trades: z.number() })
const comparison = z.object({
  exit_reasons: z.array(z.string()),
  runs: z.array(
    z.looseObject({
      run_key: z.string(),
      currency: z.string(),
      figures,
      deltas: figures.nullable(),
    })
  ),
})

/** The words before each change that a screen reader alone reads. */
const CHANGE_SAYS = "Differs from the reference's by "

/** A change of money as the comparison writes it: a plus before money above zero. */
function moneyChange(text: string, currency: string): string {
  const written = moneyText(text, currency)
  const zero = /^-?0*(\.0*)?$/.test(text)
  return text.startsWith("-") || zero ? written : `+${written}`
}

test("two runs ticked on the Runs page open their comparison, the older the reference", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const [first, second] = await theSeededRuns(page)
  await page.goto("/runs")
  const compare = page.getByTestId("runs-compare")
  await expect(compare).toBeDisabled()

  await page
    .getByRole("checkbox", { name: /^Compare demo version 2, .*stop_atr 2$/ })
    .click()
  await expect(compare).toBeDisabled()
  await page
    .getByRole("checkbox", {
      name: /^Compare demo version 1, .*stop_atr 1\.5$/,
    })
    .click()
  await expect(compare).toHaveText("Compare 2 runs")
  await page.mouse.move(700, 36)
  await screenshot(page, "runs-compare-chosen")
  await lightThemeDrawn(page, [])
  await screenshot(page, "runs-compare-chosen-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await compare.click()

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Comparison")
  await expect(page).toHaveURL(new RegExp(`runs=${first}(,|%2C)${second}$`))
  const answer = await page.request.post("/v1/runs/compare", {
    data: { runs: [first, second] },
    headers: {
      "X-CSRF-Token": z
        .object({ csrf_token: z.string() })
        .parse(await (await page.request.get("/v1/me")).json()).csrf_token,
    },
  })
  const compared = comparison.parse(await answer.json())
  const [reference, other] = compared.runs
  const legend = page.getByTestId("comparison-legend-run")
  await expect(legend).toHaveCount(2)
  await expect(legend.first()).toContainText("demo v1")
  await expect(legend.last()).toContainText("demo v2")
  await expect(page.getByTestId("compared-run").first()).toContainText(
    "Reference"
  )

  const pnl = page.getByTestId("compared-pnl").getByRole("cell")
  await expect(pnl.first()).toHaveText(
    moneyText(reference.figures.pnl, reference.currency)
  )
  if (other.deltas === null) {
    throw new Error("Expected the second run's deltas, got none.")
  }
  await expect(pnl.last()).toHaveText(
    `${moneyText(other.figures.pnl, other.currency)}${CHANGE_SAYS}${moneyChange(other.deltas.pnl, other.currency)}`
  )
  await expect(pnl.first().getByTestId("compared-change")).toHaveCount(0)
  const trades = page.getByTestId("compared-trades").getByRole("cell")
  await expect(trades.first()).toHaveText(String(reference.figures.trades))
  await expect(trades.last().getByTestId("compared-change")).toHaveText(
    CHANGE_SAYS +
      (other.deltas.trades > 0
        ? `+${other.deltas.trades}`
        : String(other.deltas.trades))
  )
  for (const reason of compared.exit_reasons) {
    await expect(page.getByTestId(`compared-${reason}-trades`)).toBeVisible()
  }
  await expect(
    page.getByTestId("comparison-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "compare")
  await lightThemeDrawn(page, ["comparison-chart"])
  await screenshot(page, "compare-light")

  await page.getByRole("link", { name: "Back to Runs" }).click()
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Runs")
  expect(errors).toEqual([])
})

test("the chart's readout follows the keys from the last trade date", async ({
  loggedIn: page,
}) => {
  const [first, second] = await theSeededRuns(page)
  await page.goto(`/runs/compare?runs=${first},${second}`)
  const chart = page.getByTestId("comparison-chart")
  await expect(chart.locator("canvas").first()).toBeVisible()
  const date = page.getByTestId("comparison-date")
  const last = await date.textContent()

  await chart.focus()
  await page.keyboard.press("Home")
  await expect(date).not.toHaveText(last === null ? "" : last)
  await page.keyboard.press("Escape")

  await expect(date).toHaveText(last === null ? "" : last)
})

test("an address of runs FEAT does not hold says so in the server's words", async ({
  loggedIn: page,
}) => {
  await page.goto(`/runs/compare?runs=${"e".repeat(64)},${"f".repeat(64)}`)

  await expect(page.getByTestId("run-results-refused")).toContainText(
    "Expected the id or the run key of a run"
  )
  await page.goto("/runs/compare?runs=nothing")
  await expect(page.getByRole("alert")).toHaveText(
    "This address names no runs to compare. Tick two to four on the Runs page."
  )
})

test("a change of the filters sets the ticks aside, and the filters they were made under bring them back", async ({
  loggedIn: page,
}) => {
  await page.goto("/runs")
  const compare = page.getByTestId("runs-compare")
  const ticked = page.getByRole("checkbox", { checked: true })
  const boxes = page.getByRole("checkbox", { name: /^Compare demo / })
  await boxes.first().click()
  await boxes.nth(1).click()
  await expect(compare).toHaveText("Compare 2 runs")

  await page.getByLabel("Strategy").click()
  await page.getByRole("option", { name: "demo" }).click()
  await expect(page).toHaveURL(/strategy=demo/)
  await expect(page.getByTestId("run-row").first()).toBeVisible()
  await expect(ticked).toHaveCount(0)
  await expect(compare).toBeDisabled()

  await page.getByLabel("Strategy").click()
  await page.getByRole("option", { name: "All", exact: true }).click()
  await expect(page).toHaveURL("/runs")
  await expect(ticked).toHaveCount(2)
  await expect(compare).toHaveText("Compare 2 runs")
})

/** The heading's grey and the accent in the dark theme, as the browser computes them. */
const HEADING = "rgb(237, 237, 237)"
const ACCENT = "rgb(252, 115, 77)"

test("a box ticks from beside it, and its border answers the pointer and the press", async ({
  loggedIn: page,
}) => {
  await page.goto("/runs")
  const box = page.getByRole("checkbox", { name: /^Compare demo / }).first()
  await expect(box).toBeVisible()
  const edge = await box.boundingBox()
  if (edge === null) {
    throw new Error("Expected the checkbox's box, got none.")
  }
  const border = () =>
    box.evaluate((element) => getComputedStyle(element).borderTopColor)

  // The design review of step 5.10: heading text under the pointer, the accent while pressed.
  await page.mouse.move(edge.x + edge.width / 2, edge.y + edge.height / 2)
  await expect.poll(border).toBe(HEADING)
  await page.mouse.down()
  await expect.poll(border).toBe(ACCENT)
  await page.mouse.up()
  await expect(box).toBeChecked()

  // 6 px beside the box, inside its target 8 px around it, a press unticks it and opens nothing.
  await page.mouse.click(edge.x - 6, edge.y + edge.height / 2)
  await expect(box).not.toBeChecked()
  await expect(page).toHaveURL("/runs")
})
