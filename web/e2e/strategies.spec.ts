import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import {
  codeEditor,
  editorLine,
  lineHolding,
  strategyFromTemplate,
  templateNamed,
  writeCode,
} from "./support/strategies.ts"

// Step 5.5, the Strategies section: a strategy made from a template, its code changed,
// validated in the server's executor, and saved as version 2 (Done means 1, the builder's check,
// recorded as a clip); a syntax error underlined at its line; the server's verdict alone drawn on
// the code (Done means 4); every parameter type of the templates at its default, with its
// refusals (Done means 2); the abandoned mark; a draft kept through a reload; and the editor's and
// the chart's code loaded with the pages that show them alone (Done means 3). Each test names a
// strategy of its own, since they share the seeded home.

test.use({ video: { mode: "on", size: { width: 1280, height: 800 } } })

/** The breakout's code with a wider stop by default, the one number the builder's check changes. */
function widerStop(code: string): string {
  return code.replace("stop_atr: float = 1.5", "stop_atr: float = 2.0")
}

test("a strategy made from a template takes a wider stop as its version 2", async ({
  loggedIn: page,
}) => {
  await page.goto("/strategies")
  await expect(
    page.getByTestId("strategy-row").filter({ hasText: "demo" })
  ).toBeVisible()
  await screenshot(page, "strategies-list")
  await page.getByRole("link", { name: "New strategy" }).click()
  await expect(
    page.locator('[data-slot="code-editor"] .cm-content')
  ).toContainText("def strategy(")
  await screenshot(page, "strategies-new")
  await page.getByLabel("Name").fill("wider_stop")
  await page.getByRole("button", { name: "Create strategy" }).click()

  await expect(page).toHaveURL(/name=wider_stop&version=1/)
  await expect(page.getByTestId("version-row")).toHaveCount(1)
  const breakout = await templateNamed(page.request, "breakout")
  await writeCode(page, widerStop(breakout.code))
  await expect(page.getByTestId("draft-state")).toHaveText("Draft, not saved")
  await page.getByRole("button", { name: "Validate" }).click()
  await expect(page.getByTestId("code-verdict")).toContainText(
    "Valid: MES, 5m bars"
  )
  await page.getByLabel("Changelog").fill("A wider stop")
  await page.getByRole("button", { name: "Save as new version" }).click()

  await expect(page).toHaveURL(/name=wider_stop&version=2/)
  const versions = page.getByTestId("version-row")
  await expect(versions).toHaveCount(2)
  await expect(versions.nth(0)).toContainText("v2")
  await expect(versions.nth(0)).toContainText("A wider stop")
  await expect(versions.nth(1)).toContainText(
    "Created from the breakout template"
  )
  await expect(codeEditor(page)).toContainText("stop_atr: float = 2.0")
  await expect(page.getByTestId("draft-state")).toHaveText(
    "Change the code to save it as a new version"
  )
  await screenshot(page, "strategy-saved-v2")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "strategy-saved-v2-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
})

test("a syntax error is underlined at its line, and nothing before Validate", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "syntax_check", "breakout")
  const breakout = await templateNamed(page.request, "breakout")
  const broken = breakout.code.replace(
    'close = pl.col("close")',
    'close = pl.col("close") +'
  )
  const line = lineHolding(broken, 'close = pl.col("close") +')
  await page.goto("/strategies/strategy?name=syntax_check")
  await expect(codeEditor(page)).toContainText("def strategy(")

  await writeCode(page, broken)
  await expect(page.locator(".cm-lintRange")).toHaveCount(0)
  await page.getByRole("button", { name: "Validate" }).click()

  await expect(
    editorLine(page, line).locator(".cm-lintRange-error")
  ).toHaveText('close = pl.col("close") +')
  await expect(page.getByTestId("code-line")).toHaveText(
    `Line ${line}: SyntaxError: invalid syntax`
  )
  await screenshot(page, "strategy-syntax-error")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "strategy-syntax-error-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  // A change takes the verdict back, which judged other code.
  await editorLine(page, line).click()
  await page.keyboard.press("End")
  await page.keyboard.press("Backspace")
  await expect(codeEditor(page)).toContainText('close = pl.col("close")')
  await expect(page.locator(".cm-lintRange")).toHaveCount(0)
  await expect(page.getByTestId("code-line")).toHaveCount(0)
})

test("Tab indents in the editor, and Escape then Tab leaves it", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "tab_keys", "breakout")
  await page.goto("/strategies/strategy?name=tab_keys")
  const editor = codeEditor(page)
  await expect(editor).toContainText("def strategy(")
  await editor.click()

  await page.keyboard.press("Tab")
  await expect(editor).toBeFocused()
  await page.keyboard.press("Escape")
  await page.keyboard.press("Tab")

  await expect(page.getByRole("button", { name: "Validate" })).toBeFocused()
  await expect(page.getByTestId("draft-state")).toHaveText("Draft, not saved")
})

test("the editor draws the server's verdict alone, at its line or listed without one", async ({
  loggedIn: page,
}) => {
  // Done means 4: the browser judges nothing itself, so a verdict the spec answers in the
  // server's place is the one the editor underlines.
  await strategyFromTemplate(page.request, "stubbed_verdict", "breakout")
  await page.goto("/strategies/strategy?name=stubbed_verdict")
  await expect(codeEditor(page)).toContainText("def strategy(")
  const answers = [
    {
      verdict: "refused",
      line: 4,
      message: "Refused at line 4 for this test.",
    },
    {
      verdict: "refused",
      line: null,
      message:
        "Expected the code to end within 60 s, got it still running then.",
    },
  ]
  await page.route("**/v1/strategies/validate", (route) =>
    route.fulfill({ json: answers.shift() })
  )

  await page.getByRole("button", { name: "Validate" }).click()
  await expect(editorLine(page, 4).locator(".cm-lintRange-error")).toHaveText(
    "import polars as pl"
  )
  await expect(page.getByTestId("code-line")).toHaveText(
    "Line 4: Refused at line 4 for this test."
  )
  await page.getByRole("button", { name: "Validate" }).click()

  await expect(page.getByTestId("code-line")).toHaveText(
    "Expected the code to end within 60 s, got it still running then."
  )
  await expect(page.locator(".cm-lintRange")).toHaveCount(0)
})

test("each template's parameters show at their defaults, and a value of another type is refused", async ({
  loggedIn: page,
}) => {
  // Done means 2: the templates declare every type the form draws between them.
  for (const name of ["breakout", "mean_reversion", "entry_window"]) {
    await strategyFromTemplate(page.request, `form_${name}`, name)
  }
  const parameters = page.getByRole("region", { name: "Parameters" })

  await page.goto("/strategies/strategy?name=form_mean_reversion")
  await expect(parameters.getByLabel("oversold")).toHaveValue("30.0")
  await expect(parameters.getByRole("radio", { name: "True" })).toBeChecked()
  await page.goto("/strategies/strategy?name=form_entry_window")
  await expect(parameters.getByRole("radio", { name: "both" })).toBeChecked()
  await expect(parameters.getByRole("radio", { name: "long" })).toBeVisible()
  await expect(parameters.getByLabel("flat_by")).toHaveValue("15:05")
  await page.goto("/strategies/strategy?name=form_breakout")
  await expect(parameters.getByLabel("lookback")).toHaveValue("12")
  await expect(parameters.getByLabel("stop_atr")).toHaveValue("1.5")
  await parameters.getByLabel("lookback").fill("12.5")
  await parameters.getByLabel("stop_atr").fill("wide")
  await parameters.getByLabel("stop_atr").blur()
  await parameters.getByLabel("lookback").blur()

  await expect(parameters).toContainText("Type a whole number, such as 12.")
  await expect(parameters).toContainText("Type a number, such as 1.5.")
  await expect(parameters.getByLabel("lookback")).toHaveAttribute(
    "aria-invalid",
    "true"
  )
  await expect(codeEditor(page)).toContainText("def strategy(")
  await screenshot(page, "strategy-parameters-refused")
})

test("a strategy marked abandoned keeps its lesson, shows on the list, and reopens", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "faded_idea", "mean_reversion")
  await page.goto("/strategies/strategy?name=faded_idea")
  const abandon = page.getByRole("region", { name: "Abandon this strategy" })
  await abandon.getByRole("button", { name: "Mark abandoned" }).click()
  await expect(abandon).toContainText("Say where the strategy broke")

  await abandon
    .getByLabel("Where it broke")
    .fill("Past 2024 the bounces ran out before the middle of the range.")
  await abandon.getByLabel("Lesson").fill("An oversold RSI alone is no edge.")
  await abandon.getByRole("button", { name: "Mark abandoned" }).click()

  const marked = page.getByRole("region", { name: "Abandoned" })
  await expect(marked).toContainText("An oversold RSI alone is no edge.")
  await expect(abandon).toHaveCount(0)
  await screenshot(page, "strategy-abandoned")
  await page.goto("/strategies")
  await expect(
    page
      .getByTestId("strategy-row")
      .filter({ hasText: "faded_idea" })
      .getByTestId("abandoned-badge")
  ).toHaveText("Abandoned")
  await screenshot(page, "strategies-list-abandoned")
  await page.goto("/strategies/strategy?name=faded_idea")
  await marked.getByRole("button", { name: "Reopen" }).click()

  await expect(abandon).toBeVisible()
  await expect(marked).toHaveCount(0)
})

test("a draft outlives a reload and leaves once discarded", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "kept_draft", "breakout")
  const breakout = await templateNamed(page.request, "breakout")
  await page.goto("/strategies/strategy?name=kept_draft")
  await expect(codeEditor(page)).toContainText("def strategy(")
  await writeCode(page, widerStop(breakout.code))

  await page.reload()
  await expect(codeEditor(page)).toContainText("stop_atr: float = 2.0")
  await expect(page.getByTestId("draft-state")).toHaveText("Draft, not saved")
  await page.getByRole("button", { name: "Discard draft" }).click()
  await page.getByRole("button", { name: "Discard", exact: true }).click()

  await expect(codeEditor(page)).toContainText("stop_atr: float = 1.5")
  await page.reload()
  await expect(codeEditor(page)).toContainText("stop_atr: float = 1.5")
  await expect(page.getByTestId("draft-state")).toHaveText(
    "Change the code to save it as a new version"
  )
})

test("the editor's code and the chart's load with the pages that show them alone", async ({
  loggedIn: page,
}) => {
  // Done means 3 (D-93, from `BACKLOG.md`): CodeMirror and Lightweight Charts each leave the
  // app's first bundle for a chunk of their own.
  const scripts: string[] = []
  page.on("request", (request) => {
    if (request.resourceType() === "script") {
      scripts.push(new URL(request.url()).pathname)
    }
  })
  const loaded = (chunk: string) =>
    scripts.some((path) => path.startsWith(`/assets/${chunk}-`))

  for (const path of ["/strategies", "/data", "/settings"]) {
    await page.goto(path)
    await page.waitForLoadState("networkidle")
  }
  expect([loaded("code-editor-codemirror"), loaded("ChartPage")]).toEqual([
    false,
    false,
  ])
  await page.goto("/strategies/new")
  await expect(
    page.locator('[data-slot="code-editor"] .cm-content')
  ).toBeVisible()
  expect([loaded("code-editor-codemirror"), loaded("ChartPage")]).toEqual([
    true,
    false,
  ])
  await page.goto("/data/chart?instrument=MES")
  await expect(page.getByTestId("price-chart")).toBeVisible()
  expect(loaded("ChartPage")).toBe(true)
})
