import { expect, test } from "./support/fixtures.ts"
import { screenshot } from "./support/screenshots.ts"
import {
  codeEditor,
  editorLine,
  keptDraftCode,
  lineHolding,
  settled,
  strategyFromTemplate,
  templateNamed,
  writeCode,
} from "./support/strategies.ts"

// Step 5.5, the Strategies section: a strategy made from a template, its code changed,
// validated in the server's executor, and saved as version 2 (Done means 1, the builder's check,
// recorded as a clip); a syntax error underlined at its line by Validate and by a save; the
// server's verdict alone drawn on the code (Done means 4); every parameter type of the templates
// at its default, with its refusals (Done means 2); the abandoned mark, made and reopened; a
// draft kept through a reload, discarded, and brought back; and the editor's and the chart's code
// loaded with the pages that show them alone (Done means 3). Each test names a strategy of its
// own, since they share the seeded home.

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
  // The version saved says so and takes the focus, so that a screen reader hears it on arrival.
  const draftState = page.getByTestId("draft-state")
  await expect(draftState).toHaveText("Saved as version 2.")
  await expect(draftState).toBeFocused()
  const code = page.getByRole("region", { name: "Code", exact: true })
  await expect(code).toContainText("Version 2 of 2")
  // It takes the focus once, on arrival: a change made and taken back leaves the focus in place.
  await editorLine(page, 9).click()
  await page.keyboard.press("End")
  await page.keyboard.type("x")
  await page.keyboard.press("Backspace")
  await expect(draftState).toHaveText("Saved as version 2.")
  await settled(page)
  await expect(codeEditor(page)).toBeFocused()
  await screenshot(page, "strategy-saved-v2")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "strategy-saved-v2-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))

  // The save forgot version 1's draft, so version 1 shows its own code.
  await versions.nth(1).click()
  await expect(page).toHaveURL(/name=wider_stop&version=1/)
  await expect(code).toContainText("Version 1 of 2")
  await expect(codeEditor(page)).toContainText("stop_atr: float = 1.5")
  await expect(draftState).toHaveText(
    "Change the code to save it as a new version"
  )
})

test("a syntax error is underlined at its line by Validate or a save, and nothing before", async ({
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

  // A save builds the code in the executor too: its refusal stands at its own line, another
  // than the verdict's, and nothing is saved.
  const entry = 'long_entry=close > pl.col("highest"),'
  const unsaved = breakout.code.replace(entry, "long_entry=close > ,")
  const entryLine = lineHolding(unsaved, "long_entry=close > ,")
  await writeCode(page, unsaved)
  await expect(page.locator(".cm-lintRange")).toHaveCount(0)
  await page.getByRole("button", { name: "Save as new version" }).click()

  await expect(
    editorLine(page, entryLine).locator(".cm-lintRange-error")
  ).toHaveText("long_entry=close > ,")
  await expect(page.getByTestId("code-line")).toHaveText(
    `Line ${entryLine}: SyntaxError: invalid syntax`
  )
  await expect(page).toHaveURL(/name=syntax_check$/)
  await expect(page.getByTestId("version-row")).toHaveCount(1)
  await editorLine(page, entryLine).click()
  await page.keyboard.press("End")
  await page.keyboard.press("Backspace")
  await expect(page.locator(".cm-lintRange")).toHaveCount(0)
  await expect(page.getByTestId("code-line")).toHaveCount(0)
})

test("Tab indents in the editor, and Escape then Tab leaves it", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "tab_keys", "breakout")
  await page.goto("/strategies/strategy?name=tab_keys")
  const editor = codeEditor(page)
  const frame = page.locator('[data-slot="code-editor"] .cm-editor')
  await expect(editor).toContainText("def strategy(")
  await expect(editor).toHaveAccessibleDescription(
    "Tab indents. Press Escape, then Tab, to leave the editor."
  )
  await editor.click()
  // The focus shows on the editor's frame, the accent's 1 px ring, as a field's does.
  await expect(frame).toHaveCSS(
    "box-shadow",
    "rgb(252, 115, 77) 0px 0px 0px 1px"
  )

  await page.keyboard.press("Tab")
  await expect(editor).toBeFocused()
  await page.keyboard.press("Escape")
  await page.keyboard.press("Tab")

  await expect(page.getByRole("button", { name: "Validate" })).toBeFocused()
  await expect(page.getByTestId("draft-state")).toHaveText("Draft, not saved")
  await expect(frame).toHaveCSS("box-shadow", "none")
  // A contrast theme of Windows drops the ring, so the frame takes the system's outline there.
  await page.emulateMedia({ forcedColors: "active" })
  await editor.click()
  await expect(frame).toHaveCSS("outline-style", "solid")
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
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "strategy-parameters-refused-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
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
  // The mark stands first on the page, far from the form that made it, so it takes the focus.
  await expect(marked).toBeFocused()
  await screenshot(page, "strategy-abandoned")
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  await screenshot(page, "strategy-abandoned-light")
  await page.evaluate(() => document.documentElement.classList.add("dark"))
  await page.goto("/strategies")
  await expect(
    page
      .getByTestId("strategy-row")
      .filter({ hasText: "faded_idea" })
      .getByTestId("abandoned-badge")
  ).toHaveText("Abandoned")
  await screenshot(page, "strategies-list-abandoned")
  await page.goto("/strategies/strategy?name=faded_idea")
  // Reopen takes the mark's words with it, so it asks once in place.
  await marked.getByRole("button", { name: "Reopen" }).click()
  await expect(abandon).toHaveCount(0)
  await marked.getByRole("button", { name: "Reopen now" }).click()

  await expect(abandon).toBeVisible()
  await expect(marked).toHaveCount(0)
  // The Code card takes the focus where the mark stood, so the next Tab enters the editor
  // rather than indenting its code.
  await expect(
    page.getByRole("region", { name: "Code", exact: true })
  ).toBeFocused()
})

test("a draft outlives a reload, and a discard acts at once until undone", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "kept_draft", "breakout")
  const breakout = await templateNamed(page.request, "breakout")
  const wider = widerStop(breakout.code)
  await page.goto("/strategies/strategy?name=kept_draft")
  await expect(codeEditor(page)).toContainText("def strategy(")
  await writeCode(page, wider)
  const draftState = page.getByTestId("draft-state")

  // Ctrl+Z in the editor undoes a discard alone, the draft's code coming back whole.
  await page.getByRole("button", { name: "Discard draft" }).click()
  await expect(draftState).toHaveText("Draft discarded")
  await codeEditor(page).click()
  await page.keyboard.press("ControlOrMeta+Z")
  await expect(draftState).toHaveText("Draft, not saved")
  await expect.poll(() => keptDraftCode(page, "kept_draft", 1)).toBe(wider)

  await page.reload()
  await expect(codeEditor(page)).toContainText("stop_atr: float = 2.0")
  await expect(draftState).toHaveText("Draft, not saved")
  await page.getByRole("button", { name: "Discard draft" }).click()

  // The same button turns to Undo discard, keeping the focus, until the next change.
  await expect(codeEditor(page)).toContainText("stop_atr: float = 1.5")
  await expect(draftState).toHaveText("Draft discarded")
  const undo = page.getByRole("button", { name: "Undo discard" })
  await expect(undo).toBeFocused()
  await undo.click()
  await expect(codeEditor(page)).toContainText("stop_atr: float = 2.0")
  await expect(draftState).toHaveText("Draft, not saved")
  await page.reload()
  await expect(codeEditor(page)).toContainText("stop_atr: float = 2.0")
  await page.getByRole("button", { name: "Discard draft" }).click()
  await page.reload()
  await expect(codeEditor(page)).toContainText("stop_atr: float = 1.5")
  await expect(draftState).toHaveText(
    "Change the code to save it as a new version"
  )
})

test("while a save runs the code waits, and a refusal at no line leaves with its code", async ({
  loggedIn: page,
}) => {
  await strategyFromTemplate(page.request, "held_save", "breakout")
  const breakout = await templateNamed(page.request, "breakout")
  await page.goto("/strategies/strategy?name=held_save")
  await expect(codeEditor(page)).toContainText("def strategy(")
  let release = () => {}
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/v1/strategies/*/versions", async (route) => {
    await released
    await route.fulfill({
      status: 400,
      contentType: "application/problem+json",
      json: {
        title: "Bad Request",
        status: 400,
        detail: "Refused for this test, at no line of the code.",
        instance: "/v1/strategies",
        request_id: "spec",
        line: null,
      },
    })
  })
  await writeCode(page, widerStop(breakout.code))
  await page.getByRole("button", { name: "Save as new version" }).click()

  // Validate would take the save's answer back, and words typed now would be lost once the
  // save opened the version it saved, so all of them wait.
  await expect(page.getByRole("button", { name: "Validate" })).toBeDisabled()
  await expect(codeEditor(page)).toHaveAttribute("aria-readonly", "true")
  await expect(page.getByLabel("Changelog")).toBeDisabled()
  release()
  const refused = page
    .getByRole("alert")
    .filter({ hasText: "Refused for this test" })
  await expect(refused).toHaveText(
    "Refused for this test, at no line of the code."
  )
  await expect(codeEditor(page)).not.toHaveAttribute("aria-readonly")
  await editorLine(page, 9).click()
  await page.keyboard.press("End")
  await page.keyboard.type(" ")
  await expect(refused).toHaveCount(0)
})

test("while a create runs the template waits, and the strategy opens once saved", async ({
  loggedIn: page,
}) => {
  await page.goto("/strategies/new")
  await expect(
    page.locator('[data-slot="code-editor"] .cm-content')
  ).toContainText("def strategy(")
  let release = () => {}
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/v1/strategies", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback()
      return
    }
    await released
    await route.continue()
  })
  await page.getByLabel("Name").fill("held_create")
  await page.getByRole("button", { name: "Create strategy" }).click()

  // Another template would draw another form, whose create would never hear the answer.
  const templates = page.getByTestId("template-choice").getByRole("button")
  await expect(templates.first()).toBeDisabled()
  release()
  await expect(page).toHaveURL(/name=held_create&version=1/)
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
