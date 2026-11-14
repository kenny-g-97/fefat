import type { Page } from "@playwright/test"

/** The errors `page` logs from now on, to the console or as an uncaught exception, which a spec
 * expects to be none. */
export function consoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text())
    }
  })
  page.on("pageerror", (error) => errors.push(error.message))
  return errors
}
