import { expect, it } from "vitest"
import comparisonChart from "./ComparisonChart.tsx?raw"
import equityChart from "./EquityChart.tsx?raw"
import fanChart from "./FanChart.tsx?raw"
import histogram from "./Histogram.tsx?raw"
import percentileChart from "./PercentileChart.tsx?raw"
import chart from "./PriceChart.tsx?raw"
import readme from "./README.md?raw"
import drawn from "./drawn-series.ts?raw"

/** The fields of the type `name` in `source`, a `Readonly<{ … }>` of one level. */
function fields(source: string, name: string): readonly string[] {
  const block = new RegExp(`type ${name} = Readonly<\\{([^}]*)\\}>`).exec(
    source
  )
  if (block === null) {
    throw new Error(`Expected the type ${name} in its module, got none.`)
  }
  return [...block[1].matchAll(/^\s*(\w+)\??:/gm)].map((match) => match[1])
}

it("documents every prop of PriceChart and every field of its panes and series", () => {
  // Done means 3 of step 5.4: `PriceChart` is documented in web/src/charts/README.md.
  const named = [
    ...fields(chart, "PriceChartProps"),
    ...fields(drawn, "ChartPane"),
    ...fields(drawn, "CandleSeries"),
    ...fields(drawn, "HistogramSeries"),
    ...fields(drawn, "LineSeries"),
  ]

  expect(named.length).toBeGreaterThan(20)
  expect(named.filter((name) => !readme.includes(`\`${name}\``))).toEqual([])
})

it("documents every prop of the results' charts", () => {
  // Step 5.7: the two charts of a finished run's page, step 5.20's fan, step 5.21's figures
  // against the percent of paths, step 5.23's buy and hold on the equity chart, and step 5.10's
  // comparison of runs.
  const named = [
    ...fields(equityChart, "EquityChartProps"),
    ...fields(histogram, "HistogramChartProps"),
    ...fields(fanChart, "FanChartProps"),
    ...fields(percentileChart, "PercentileChartProps"),
    ...fields(comparisonChart, "ComparisonChartProps"),
  ]

  expect(named.length).toBe(27)
  expect(named.filter((name) => !readme.includes(`\`${name}\``))).toEqual([])
})
