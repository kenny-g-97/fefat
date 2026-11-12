import { describe, expect, it } from "vitest"
import type { ChartStyle } from "@/api/settings"
import { chartLook, type ThemeTokens, withAlpha } from "./chart-look"

const DARK: ThemeTokens = {
  foreground: "#ededed",
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

describe("withAlpha", () => {
  it("writes a colour at an alpha, and refuses a colour of another form", () => {
    expect(withAlpha("#ff4d6d", 0.06)).toBe("rgba(255, 77, 109, 0.06)")
    expect(() => withAlpha("teal", 0.5)).toThrow(
      'Expected a colour as #rrggbb, got "teal".'
    )
  })
})
