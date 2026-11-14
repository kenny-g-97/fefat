import { expect, test } from "./support/fixtures.ts"

// The content security policy of step 5.4 (D-93): styles written into the page apply, which the
// chart library's logo needs, while a script written into the page stays refused.

test("a style written into the page applies, and a script written into it never runs", async ({
  loggedIn: page,
}) => {
  const errors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text())
    }
  })
  await page.goto("/data")
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

  const written = await page.evaluate(() => {
    const style = document.createElement("style")
    style.textContent = "#policy-probe { width: 123px }"
    document.head.append(style)
    const probe = document.createElement("div")
    probe.id = "policy-probe"
    document.body.append(probe)
    const script = document.createElement("script")
    script.textContent = "document.body.dataset.policyProbe = 'ran'"
    document.head.append(script)
    return {
      width: getComputedStyle(probe).width,
      ran: document.body.dataset.policyProbe === "ran",
    }
  })

  expect(written).toEqual({ width: "123px", ran: false })
  expect(errors).toEqual([
    expect.stringMatching(/inline script.*Content Security Policy/),
  ])
})
