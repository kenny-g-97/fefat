import { expect, it } from "vitest"
import manifest from "../../package.json?raw"
import echartsNotice from "../../node_modules/echarts/NOTICE?raw"
import { EQUITY_CHART_NOTICE } from "./attribution"

it("shows the notice of the version of the chart library the app installs", () => {
  // CHART_NOTICE is a hand copy of the NOTICE file at the library's tag v5.2.1, which its npm
  // package does not ship. At an upgrade, read that file at the new tag, bring the copy and
  // the settings spec's to it, and then this version.
  expect(manifest).toContain('"lightweight-charts": "5.2.1"')
})

it("shows the notice of the installed ECharts word for word", () => {
  // ECharts ships its NOTICE file: at an upgrade this fails where its words change.
  const { product, copyright, credit, page } = EQUITY_CHART_NOTICE
  expect(echartsNotice.replace(/\r?\n+/g, " ").trim()).toBe(
    `${product} ${copyright} ${credit} (${page}).`
  )
})
