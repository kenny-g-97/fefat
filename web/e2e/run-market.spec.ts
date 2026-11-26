import type { Page } from "@playwright/test"
import { z } from "zod"
import { chartPictures, lightThemeDrawn } from "./support/chart.ts"
import { consoleErrors } from "./support/console.ts"
import { lowContrastInEachTheme } from "./support/contrast.ts"
import {
  countText,
  figureMoney,
  figureText,
  moneyText,
  shareText,
} from "./support/figures.ts"
import { expect, test } from "./support/fixtures.ts"
import {
  COUNTED,
  countedAnswer,
  type Days,
  exposure,
  type Held,
  SIZED_LOTS,
  withExposure,
} from "./support/market-answers.ts"
import { problemAnswer } from "./support/problems.ts"
import { screenshot } from "./support/screenshots.ts"
import { theSeededKey } from "./support/seeded-run.ts"

// A run's market exposure of step 5.23 against the seeded server: every figure of its card, and
// buy and hold beside the equity, is the API's (Done means 1, its other half in
// python/tests/server/test_http_run_results.py), read here with the spec's own formatting. The
// seeded run's two trade dates count no exposure, which its own answer shows; the figures a run
// of more days counts are drawn from an answer the spec gives (`countedAnswer`), the server's own
// one lot kept and its curve at the equity's own decisions, as step 5.22's spec gives a run of
// both sides.

const statistics = z.looseObject({
  currency: z.string(),
  metrics: z.looseObject({
    pnl: z.string(),
    drawdown: z.looseObject({
      max_drawdown: z.string(),
      longest_drawdown_days: z.number(),
    }),
    daily: z.looseObject({ sharpe: z.number().nullable() }),
  }),
})

const NONE = "None"
/** What stands between a stat's figure and its unit, as the page writes it. */
const NO_BREAK_SPACE = String.fromCharCode(0xa0)
const WHY: Readonly<Record<string, string>> = {
  too_few_days: "Needs 3 days",
  market_never_differed: "The market's days never differed",
  run_never_differed: "The run's days never differed",
}
const HELD =
  "Buy and hold buys at the run's first mark and holds to its last, paying no fee, slippage, or funding."

/** The run's market exposure and statistics, as the server answers them. */
async function answersOf(page: Page, key: string) {
  const [market, stats] = await Promise.all([
    page.request.get(`/v1/runs/${key}/market`),
    page.request.get(`/v1/runs/${key}/stats`),
  ])
  const { currency, metrics } = statistics.parse(await stats.json())
  return { answer: exposure.parse(await market.json()), currency, metrics }
}

/** Why `side`'s figures read None, as the page says it. */
function why(side: Days): string {
  if (side.uncounted === null) {
    throw new Error("Expected why a figure reads None, got no reason.")
  }
  return WHY[side.uncounted]
}

/** What a stat's line says: its days, or why its figure reads None. */
function detail(figure: number | null, side: Days): string {
  return figure === null ? why(side) : `Over ${countText(side.days, "day")}`
}

function lower(words: string): string {
  return `${words.charAt(0).toLowerCase()}${words.slice(1)}`
}

/** The line of the falling and the rising days, as the page writes it. */
function sidesText(falling: Days, rising: Days): string {
  const one = (side: Days, moved: string) => {
    if (side.days === 0) {
      return `The market ${moved} on no day.`
    }
    const correlation =
      side.correlation === null ? NONE : figureText(side.correlation)
    const beta =
      side.beta_lots === null ? NONE : `${figureText(side.beta_lots)} lots`
    const reason = side.uncounted === null ? "" : `, ${lower(why(side))}`
    return `Over the ${countText(side.days, "day")} the market ${moved}: correlation ${correlation}, beta ${beta}${reason}.`
  }
  return `${one(falling, "fell")}\n${one(rising, "rose")}`
}

/** What a column of the table holds, the run's own figures or buy and hold's at one size. */
type Figures = Readonly<
  Pick<Held, "net_pnl" | "max_drawdown" | "longest_drawdown_days" | "sharpe">
>

/** A column of the table: its figures as the page writes them, row by row. */
function columnOf(
  figures: Figures | null,
  currency: string
): readonly string[] {
  if (figures === null) {
    return [NONE, NONE, NONE, NONE]
  }
  return [
    moneyText(figures.net_pnl, currency),
    moneyText(figures.max_drawdown, currency),
    countText(figures.longest_drawdown_days, "day"),
    figures.sharpe === null ? NONE : figureText(figures.sharpe),
  ]
}

/** How many pixels of the equity's pane, the top 65 % of its canvas, lie within a smoothed
 * edge's distance of `colour` once painted over the card, as the line's own pixels do. */
async function pixelsNear(page: Page, colour: string): Promise<number> {
  const [picture] = await chartPictures(page, ["equity-chart"])
  const card = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--card")
  )
  return page.evaluate(
    async ([source, near, under]) => {
      const channels = (hex: string) => {
        const digits = hex.trim().slice(1)
        const full =
          digits.length === 3
            ? [...digits].map((digit) => digit + digit).join("")
            : digits
        return [0, 2, 4].map((at) => parseInt(full.slice(at, at + 2), 16))
      }
      const image = new Image()
      image.src = source
      await image.decode()
      const canvas = document.createElement("canvas")
      canvas.width = image.width
      canvas.height = image.height
      const context = canvas.getContext("2d")
      if (context === null) {
        throw new Error("Expected a 2D canvas to count on, got none.")
      }
      context.drawImage(image, 0, 0)
      const rows = Math.floor(image.height * 0.65)
      const pixels = context.getImageData(0, 0, image.width, rows).data
      const [target, background] = [channels(near), channels(under)]
      let counted = 0
      for (let at = 0; at < pixels.length; at += 4) {
        const alpha = pixels[at + 3] / 255
        const shown = [0, 1, 2].map(
          (part) => alpha * pixels[at + part] + (1 - alpha) * background[part]
        )
        const off = Math.hypot(
          ...shown.map((value, part) => value - target[part])
        )
        counted += off <= 32 ? 1 : 0
      }
      return counted
    },
    [picture, colour, card] as const
  )
}

/** The theme's second series colour as the page holds it now. */
function chartSecond(page: Page): Promise<string> {
  return page.evaluate(() =>
    getComputedStyle(document.documentElement)
      .getPropertyValue("--chart-2")
      .trim()
  )
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" })
})

test("a run's market exposure is the API's, beside buy and hold at both sizes", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { currency, metrics } = await answersOf(page, key)
  const given = await countedAnswer(page, key)
  await withExposure(page, key, given)
  const every = given.all_days

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Market exposure" })
  await expect(card).toBeVisible()
  await expect(page.getByTestId("market-correlation")).toContainText(
    figureText(COUNTED.all_days.correlation)
  )
  await expect(page.getByTestId("market-beta")).toContainText(
    `${figureText(COUNTED.all_days.beta_lots)}${NO_BREAK_SPACE}lots`
  )
  await expect(page.getByTestId("market-alpha")).toContainText(
    figureMoney(COUNTED.all_days.alpha, currency)
  )
  await expect(page.getByTestId("market-explained")).toContainText(
    shareText(COUNTED.all_days.explained_share)
  )
  const stats = [
    ["correlation", every.correlation],
    ["beta", every.beta_lots],
    ["alpha", every.alpha],
    ["explained", every.explained_share],
  ] as const
  for (const [stat, figure] of stats) {
    await expect(page.getByTestId(`market-${stat}`)).toContainText(
      detail(figure, every)
    )
  }
  await expect(page.getByTestId("market-sides")).toHaveText(
    sidesText(given.falling_days, given.rising_days)
  )
  const table = page.getByTestId("buy-and-hold")
  await expect(table.getByRole("columnheader")).toHaveText([
    "Figure",
    "This run",
    "Buy and hold",
    "1 lot",
    `${figureText(SIZED_LOTS)} lots`,
  ])
  const run = {
    net_pnl: metrics.pnl,
    max_drawdown: metrics.drawdown.max_drawdown,
    longest_drawdown_days: metrics.drawdown.longest_drawdown_days,
    sharpe: metrics.daily.sharpe,
  }
  const held = given.buy_and_hold
  if (held.kind !== "sized") {
    throw new Error(
      "Expected the given buy and hold sized at the run's volatility."
    )
  }
  const columns = [run, held.at_one_lot, held.at_run_volatility].map((each) =>
    columnOf(each, currency)
  )
  for (const [at, row] of [
    "net-pnl",
    "max-drawdown",
    "longest-spell",
    "sharpe",
  ].entries()) {
    await expect(
      page.getByTestId(`buy-and-hold-${row}`).getByRole("cell"),
      row
    ).toHaveText(columns.map((column) => column[at]))
  }
  await expect(page.getByTestId("buy-and-hold-note")).toHaveText(
    `${HELD} At the run's volatility it holds the lots whose days move as much as the run's; its Sharpe and its spell under a peak stay one lot's.`
  )
  const robustness = await page
    .getByRole("region", { name: "Robustness" })
    .boundingBox()
  const equity = await page
    .getByRole("region", { name: "Equity" })
    .boundingBox()
  const shown = await card.boundingBox()
  if (robustness === null || equity === null || shown === null) {
    throw new Error("Expected the page's cards drawn, got one without a box.")
  }
  expect(robustness.y).toBeLessThan(shown.y)
  expect(shown.y).toBeLessThan(equity.y)
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await screenshot(page, "run-market")
  await lightThemeDrawn(page, ["equity-chart"])
  await screenshot(page, "run-market-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("buy and hold is the equity chart's second line, named in its legend and read in its readout", async ({
  loggedIn: page,
}) => {
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { currency } = await answersOf(page, key)
  const given = await countedAnswer(page, key)
  await withExposure(page, key, given)
  const held = given.buy_and_hold
  if (held.kind !== "sized") {
    throw new Error(
      "Expected the given buy and hold sized at the run's volatility."
    )
  }
  const walk = held.curve
  const last = walk.equity.length - 1

  await page.goto(`/runs/run?key=${key}`)

  const chart = page.getByTestId("equity-chart")
  const readout = page.getByTestId("equity-buy-and-hold")
  await expect(chart.locator("canvas").first()).toBeVisible()
  await expect(page.getByTestId("equity-legend-buy-and-hold")).toHaveText(
    `Buy and hold, ${figureText(SIZED_LOTS)} lots`
  )
  await expect(readout).toHaveText(figureMoney(walk.equity[last], currency))
  await chart.focus()
  await page.keyboard.press("Home")
  await expect(readout).toHaveText(figureMoney(walk.equity[0], currency))
  await page.keyboard.press("ArrowRight")
  await expect(readout).toHaveText(figureMoney(walk.equity[1], currency))
  await page.keyboard.press("Escape")
  await expect(readout).toHaveText(figureMoney(walk.equity[last], currency))
  await page.mouse.move(700, 36)
  await expect
    .poll(async () => pixelsNear(page, await chartSecond(page)))
    .toBeGreaterThan(200)
  await lightThemeDrawn(page, ["equity-chart"])
  await expect
    .poll(async () => pixelsNear(page, await chartSecond(page)))
    .toBeGreaterThan(200)
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  expect(errors).toEqual([])
})

test("a run of two days counts no exposure, and its chart draws no second line", async ({
  loggedIn: page,
}) => {
  // The seeded run's own answer: under three days every figure reads None and says why, buy and
  // hold at one lot still counts, and the chart draws no cyan.
  const errors = consoleErrors(page)
  const key = await theSeededKey(page)
  const { answer, currency, metrics } = await answersOf(page, key)
  expect(answer.all_days.uncounted).toBe("too_few_days")
  expect(answer.buy_and_hold.kind).toBe("unsized")

  await page.goto(`/runs/run?key=${key}`)

  for (const stat of ["correlation", "beta", "alpha", "explained"]) {
    const shown = page.getByTestId(`market-${stat}`)
    await expect(shown).toContainText(NONE)
    await expect(shown).toContainText("Needs 3 days")
  }
  await expect(page.getByTestId("market-sides")).toHaveText(
    sidesText(answer.falling_days, answer.rising_days)
  )
  await expect(
    page.getByTestId("buy-and-hold").getByRole("columnheader").last()
  ).toHaveText("Run's volatility")
  await expect(
    page.getByTestId("buy-and-hold-net-pnl").getByRole("cell")
  ).toHaveText([
    moneyText(metrics.pnl, currency),
    moneyText(answer.buy_and_hold.at_one_lot.net_pnl, currency),
    NONE,
  ])
  await expect(page.getByTestId("buy-and-hold-note")).toHaveText(
    `${HELD} At the run's volatility it reads None: needs 3 days.`
  )
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await page.mouse.move(700, 36)
  await expect(page.getByTestId("equity-legend")).toHaveText(
    "Above the capitalBelow the capitalDrawdownCapital"
  )
  await expect(page.getByTestId("equity-buy-and-hold")).toHaveCount(0)
  expect(await pixelsNear(page, await chartSecond(page))).toBeLessThan(20)
  // The ui-verifier's note: the card as a run of two days shows it, for the pull request.
  await screenshot(page, "run-market-uncounted")
  expect(errors).toEqual([])
})

test("while the market exposure is read, its card keeps its room and the chart waits", async ({
  loggedIn: page,
}) => {
  // The card's figures arrive after the cards above it, and the equity card under it stays put;
  // its chart waits for the answer and draws once, so that buy and hold never rescales it (the
  // design review).
  const key = await theSeededKey(page)
  const given = await countedAnswer(page, key)
  let release = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**/v1/runs/${key}/market`, async (route) => {
    await held
    const answered = await route.fetch()
    await route.fulfill({ response: answered, json: given })
  })

  await page.goto(`/runs/run?key=${key}`)

  const equity = page.getByRole("region", { name: "Equity" })
  await expect(page.getByTestId("market-reading")).toBeVisible()
  await expect(page.getByTestId("equity-waiting")).toBeVisible()
  await expect(equity.locator("canvas")).toHaveCount(0)
  await expect(page.getByTestId("equity-legend-buy-and-hold")).toHaveCount(0)
  const before = await equity.boundingBox()
  release()
  await expect(page.getByTestId("market-figures")).toBeVisible()
  await expect(equity.locator("canvas").first()).toBeVisible()
  await expect(page.getByTestId("equity-legend-buy-and-hold")).toBeVisible()
  const after = await equity.boundingBox()
  if (before === null || after === null) {
    throw new Error("Expected the equity card drawn, got no box.")
  }
  expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual(4)
})

test("a refused market exposure says why in its card alone", async ({
  loggedIn: page,
}) => {
  const key = await theSeededKey(page)
  const refusal =
    "Expected a mark at a decision of run 0123456789ab, got none: its account was never valued at a tradeable price."
  await page.route(`**/v1/runs/${key}/market`, (route) =>
    route.fulfill(problemAnswer(409, refusal))
  )

  await page.goto(`/runs/run?key=${key}`)

  const card = page.getByRole("region", { name: "Market exposure" })
  await expect(card.getByTestId("run-results-refused")).toHaveText(refusal)
  await expect(card.getByRole("button", { name: "Try again" })).toHaveCount(0)
  await expect(page.getByTestId("key-figures")).toBeVisible()
  await expect(
    page.getByTestId("equity-chart").locator("canvas").first()
  ).toBeVisible()
  await expect(page.getByTestId("equity-legend-buy-and-hold")).toHaveCount(0)
})

test("the market exposure reads in both themes, under the motion floor", async ({
  loggedIn: page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  const key = await theSeededKey(page)
  await withExposure(page, key, await countedAnswer(page, key))

  await page.goto(`/runs/run?key=${key}`)

  await expect(page.getByTestId("market-figures")).toBeVisible()
  await expect(page.getByTestId("equity-legend-buy-and-hold")).toBeVisible()
  expect(await lowContrastInEachTheme(page)).toEqual([])
  await page.evaluate(() => document.documentElement.classList.add("dark"))
})
