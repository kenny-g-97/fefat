import type { Page } from "@playwright/test"
import { z } from "zod"
import { lightThemeDrawn } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { moneyText } from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"

// The comparison of step 5.10 (D-126) against the seeded server: the two saved runs of demo, its
// version 1 and version 2's wider stop, ticked on the Runs page, open their comparison, the older
// the reference, whose figures and changes are the API's, read here with the spec's own
// formatting (Done means 1 for the comparison; its deltas are the stored metrics' differences in
// python/tests/server/test_http_runs_compare.py).

test.use({ timezoneId: "UTC" })

const listed = z.object({
  runs: z.array(
    z.looseObject({
      run_key: z.string(),
      strategy: z.looseObject({ version: z.number() }).nullable(),
    })
  ),
})

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

/** The seed's run of each version of demo, the oldest of each, which other specs leave as they
 * are: version 1's is `demo-run-01`. */
async function theSeededRuns(page: Page): Promise<readonly [string, string]> {
  const answer = await page.request.get("/v1/runs", {
    params: { strategy: "demo", status: "succeeded" },
  })
  const { runs } = listed.parse(await answer.json())
  const oldestOf = (version: number) => {
    const found = runs.filter((run) => run.strategy?.version === version).at(-1)
    if (found === undefined) {
      throw new Error(
        `Expected the seed's run of demo version ${version}, got none.`
      )
    }
    return found.run_key
  }
  return [oldestOf(1), oldestOf(2)]
}

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
    `${moneyText(other.figures.pnl, other.currency)}${moneyChange(other.deltas.pnl, other.currency)}`
  )
  await expect(pnl.first().getByTestId("compared-change")).toHaveCount(0)
  const trades = page.getByTestId("compared-trades").getByRole("cell")
  await expect(trades.first()).toHaveText(String(reference.figures.trades))
  await expect(trades.last().getByTestId("compared-change")).toHaveText(
    other.deltas.trades > 0
      ? `+${other.deltas.trades}`
      : String(other.deltas.trades)
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
