import { expect, it } from "vitest"
import manifest from "../../package.json?raw"

it("shows the notice of the version of the chart library the app installs", () => {
  // CHART_NOTICE is a hand copy of the NOTICE file at the library's tag v5.2.1, which its npm
  // package does not ship. At an upgrade, read that file at the new tag, bring the copy and
  // the settings spec's to it, and then this version.
  expect(manifest).toContain('"lightweight-charts": "5.2.1"')
})
