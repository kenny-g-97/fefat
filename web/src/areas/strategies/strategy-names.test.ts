import { describe, expect, it } from "vitest"
import { z } from "zod"
import document from "../../../openapi.json?raw"
import { STRATEGY_NAME, strategyName, strategySearch } from "./strategy-names"

const newStrategy = z.object({
  components: z.object({
    schemas: z.object({
      NewStrategy: z.object({
        properties: z.object({ name: z.object({ pattern: z.string() }) }),
      }),
    }),
  }),
})

describe("strategyName", () => {
  it("is the rule the API holds a new strategy's name to", () => {
    const api = newStrategy.parse(JSON.parse(document))

    expect(STRATEGY_NAME.source).toBe(
      api.components.schemas.NewStrategy.properties.name.pattern
    )
  })

  it("takes a lower-case identifier and refuses what no folder takes", () => {
    const read = [
      "breakout_2",
      "Breakout",
      "2breakout",
      "con",
      "a".repeat(65),
    ].map((name) => strategyName.safeParse(name).success)

    expect(read).toEqual([true, false, false, false, false])
  })
})

describe("strategySearch", () => {
  it("reads a strategy's name and version, and leaves out what it cannot read", () => {
    expect([
      strategySearch.parse({ name: "breakout", version: 2 }),
      strategySearch.parse({ name: "../outside", version: 0 }),
      strategySearch.parse({}),
    ]).toEqual([
      { name: "breakout", version: 2 },
      { name: undefined, version: undefined },
      { name: undefined, version: undefined },
    ])
  })
})
