import { type APIRequestContext, expect, type Page } from "@playwright/test"
import { z } from "zod"

const identity = z.object({ csrf_token: z.string() })
const template = z.object({
  name: z.string(),
  hypothesis: z.string(),
  code: z.string(),
})

/** The template FEAT ships under `name`, as `GET /v1/strategies/templates` gives it. */
export async function templateNamed(
  request: APIRequestContext,
  name: string
): Promise<z.infer<typeof template>> {
  const listed = z
    .array(template)
    .parse(await (await request.get("/v1/strategies/templates")).json())
  const found = listed.find((each) => each.name === name)
  if (found === undefined) {
    throw new Error(
      `Expected the template ${name}, got ${listed.map((each) => each.name).join(", ")}.`
    )
  }
  return found
}

/** A strategy `name` made through the API from the template `templateName`, as its version 1,
 * for a spec whose subject is the strategy's page rather than New strategy. */
export async function strategyFromTemplate(
  request: APIRequestContext,
  name: string,
  templateName: string
): Promise<void> {
  const { csrf_token } = identity.parse(
    await (await request.get("/v1/me")).json()
  )
  const copied = await templateNamed(request, templateName)
  const made = await request.post("/v1/strategies", {
    data: {
      name,
      code: copied.code,
      hypothesis: copied.hypothesis,
      changelog: `Made for the spec from the ${templateName} template`,
    },
    headers: { "X-CSRF-Token": csrf_token },
  })
  expect(made.status()).toBe(201)
}

/** The editor of the strategy page, CodeMirror's text, named for its strategy. */
export function codeEditor(page: Page) {
  return page.getByRole("textbox", { name: /^Code of / })
}

/** Write `code` over the editor's whole text, as a paste would. */
export async function writeCode(page: Page, code: string): Promise<void> {
  const editor = codeEditor(page)
  await editor.click()
  await page.keyboard.press("ControlOrMeta+A")
  await page.keyboard.insertText(code)
}

/** The line of `code`, counting from 1, that holds `text`. */
export function lineHolding(code: string, text: string): number {
  const index = code.split("\n").findIndex((line) => line.includes(text))
  if (index === -1) {
    throw new Error(`Expected a line holding ${text}, got none.`)
  }
  return index + 1
}

/** The editor's line `line`, counting from 1, as CodeMirror draws it. */
export function editorLine(page: Page, line: number) {
  return page.locator('[data-slot="code-editor"] .cm-line').nth(line - 1)
}
