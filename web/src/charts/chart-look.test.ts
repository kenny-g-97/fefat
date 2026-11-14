import { describe, expect, it } from "vitest"
import type { ChartStyle } from "@/api/settings"
import {
  chartLook,
  lastBarColour,
  legibleText,
  type ThemeTokens,
  tokenColour,
  withAlpha,
} from "./chart-look"

const DARK: ThemeTokens = {
  card: "#0a0a0a",
  mutedForeground: "#7c7c7c",
  border: "#1a1a1a",
  input: "#666666",
  accent: "#1a1a1a",
  brand: "#fc734d",
  positive: "#10b981",
  negative: "#ff4d6d",
}
const THEMES_OWN = {
  up: null,
  down: null,
  background: null,
  grid: null,
  text: null,
}
const FEATS: ChartStyle = {
  up_body: "hollow",
  down_body: "hollow",
  volume_shown: true,
  volume_colouring: "neutral",
  grid_shown: true,
  sessions_shaded: true,
  dark: THEMES_OWN,
  light: THEMES_OWN,
}
const CLEAR = "rgba(0, 0, 0, 0)"

describe("chartLook", () => {
  it("draws FEAT's style as hollow candles in the sign colours on a clear background", () => {
    const look = chartLook(FEATS, "dark", DARK)

    expect([look.up, look.down, look.upBody, look.downBody]).toEqual([
      "#10b981",
      "#ff4d6d",
      CLEAR,
      CLEAR,
    ])
    expect([look.background, look.text, look.grid]).toEqual([
      CLEAR,
      "#7c7c7c",
      "#1a1a1a",
    ])
    expect([look.volume, look.volumeByDirection]).toEqual(["#666666", false])
    expect([look.gridShown, look.sessionsShaded]).toEqual([true, true])
  })

  it("fills a body and takes the trader's colours in the theme they were picked in alone", () => {
    const style: ChartStyle = {
      ...FEATS,
      down_body: "filled",
      volume_colouring: "direction",
      dark: { ...THEMES_OWN, up: "#26a69a", background: "#000000" },
    }

    const dark = chartLook(style, "dark", DARK)
    const light = chartLook(style, "light", DARK)

    expect([dark.up, dark.upBody, dark.downBody, dark.background]).toEqual([
      "#26a69a",
      CLEAR,
      "#ff4d6d",
      "#000000",
    ])
    expect([dark.volumeUp, dark.volumeByDirection]).toEqual([
      "rgba(38, 166, 154, 0.5)",
      true,
    ])
    expect([light.up, light.background]).toEqual(["#10b981", CLEAR])
  })
})

describe("lastBarColour", () => {
  it("colours the last price as its bar's direction, which a hollow body leaves clear", () => {
    const look = chartLook(FEATS, "dark", DARK)

    expect(lastBarColour(look, [10, 12], [11, 12])).toBe("#10b981")
    expect(lastBarColour(look, [10, 12], [11, 11.75])).toBe("#ff4d6d")
    expect(lastBarColour(look, [], [])).toBe("#10b981")
  })
})

describe("legibleText", () => {
  it("writes ink on the dark theme's sign colours and white on the light theme's", () => {
    // Step 5.4's design review: the library wrote white on the dark theme's green, 2.5 : 1.
    expect(
      ["#10b981", "#ff4d6d", "#0a7a4c", "#c81e4a"].map((colour) =>
        legibleText(colour)
      )
    ).toEqual(["#050505", "#050505", "#ffffff", "#ffffff"])
  })
})

describe("tokenColour", () => {
  it("reads a token as #rrggbb, the short form the built styles write as well", () => {
    expect(tokenColour("--input", "#666")).toBe("#666666")
    expect(tokenColour("--card", " #0a0a0a")).toBe("#0a0a0a")
    expect(() => tokenColour("--brand", "oklch(0.7 0.2 40)")).toThrow(
      'Expected the token --brand as #rrggbb, got "oklch(0.7 0.2 40)".'
    )
  })
})

describe("withAlpha", () => {
  it("writes a colour at an alpha, and refuses a colour of another form", () => {
    expect(withAlpha("#ff4d6d", 0.06)).toBe("rgba(255, 77, 109, 0.06)")
    expect(() => withAlpha("teal", 0.5)).toThrow(
      'Expected a colour as #rrggbb, got "teal".'
    )
  })
})
