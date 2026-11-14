import { expect, it } from "vitest"
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
  ]

  expect(named.length).toBeGreaterThan(20)
  expect(named.filter((name) => !readme.includes(`\`${name}\``))).toEqual([])
})
