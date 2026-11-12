import type { ChartStyle, Theme } from "@/api/settings"

/** The design system's tokens a chart paints with (web/DESIGN.md, Palette), read from the page
 * in the theme it shows. */
export type ThemeTokens = Readonly<{
  foreground: string
  mutedForeground: string
  border: string
  input: string
  accent: string
  brand: string
  positive: string
  negative: string
}>

/** How a marker reads: quiet, the accent, or the sign of a profit or a loss. */
export type MarkerTone = "subtle" | "accent" | "positive" | "negative"

/** Every colour and choice a chart draws with, from the trader's style in the theme shown. */
export type ChartLook = Readonly<{
  background: string
  text: string
  grid: string
  gridShown: boolean
  up: string
  down: string
  upBody: string
  downBody: string
  volume: string
  volumeUp: string
  volumeDown: string
  volumeByDirection: boolean
  sessionShade: string
  sessionsShaded: boolean
  crosshair: string
  crosshairLabel: string
  markers: Readonly<Record<MarkerTone, string>>
}>

const CLEAR = "rgba(0, 0, 0, 0)"
const TOKENS: Readonly<Record<keyof ThemeTokens, string>> = {
  foreground: "--foreground",
  mutedForeground: "--muted-foreground",
  border: "--border",
  input: "--input",
  accent: "--accent",
  brand: "--brand",
  positive: "--positive",
  negative: "--negative",
}

/** The look of `style` in `theme`, each colour the trader's own or else the theme's token: rising
 * bars in the positive sign colour and falling ones in the negative, the trader's exception to
 * "colour means sign" (web/DESIGN.md), hollow bodies clear, the background clear so that the
 * card shows through, and the sessions shaded by a breath of the text colour. */
export function chartLook(
  style: ChartStyle,
  theme: Theme,
  tokens: ThemeTokens
): ChartLook {
  // A colour left out, as null, is the theme's own.
  const own = style[theme]
  const up = own.up ?? tokens.positive
  const down = own.down ?? tokens.negative
  const text = own.text ?? tokens.mutedForeground
  return {
    background: own.background ?? CLEAR,
    text,
    grid: own.grid ?? tokens.border,
    gridShown: style.grid_shown,
    up,
    down,
    upBody: style.up_body === "filled" ? up : CLEAR,
    downBody: style.down_body === "filled" ? down : CLEAR,
    volume: tokens.input,
    volumeUp: withAlpha(up, 0.5),
    volumeDown: withAlpha(down, 0.5),
    volumeByDirection: style.volume_colouring === "direction",
    sessionShade: withAlpha(text, 0.06),
    sessionsShaded: style.sessions_shaded,
    crosshair: tokens.input,
    crosshairLabel: tokens.accent,
    markers: {
      subtle: tokens.mutedForeground,
      accent: tokens.brand,
      positive: tokens.positive,
      negative: tokens.negative,
    },
  }
}

/** The tokens of the theme the page shows now, as `#rrggbb`. */
export function readThemeTokens(): ThemeTokens {
  const computed = getComputedStyle(document.documentElement)
  const read = (name: string) => {
    const value = computed.getPropertyValue(name).trim()
    if (!/^#[0-9a-f]{6}$/i.test(value)) {
      throw new Error(
        `Expected the token ${name} as #rrggbb, got ${JSON.stringify(value)}.`
      )
    }
    return value
  }
  return {
    foreground: read(TOKENS.foreground),
    mutedForeground: read(TOKENS.mutedForeground),
    border: read(TOKENS.border),
    input: read(TOKENS.input),
    accent: read(TOKENS.accent),
    brand: read(TOKENS.brand),
    positive: read(TOKENS.positive),
    negative: read(TOKENS.negative),
  }
}

/** `colour`, `#rrggbb`, at `alpha`. */
export function withAlpha(colour: string, alpha: number): string {
  const channels = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(colour)
  if (channels === null) {
    throw new Error(
      `Expected a colour as #rrggbb, got ${JSON.stringify(colour)}.`
    )
  }
  const [, red, green, blue] = channels
  return `rgba(${parseInt(red, 16)}, ${parseInt(green, 16)}, ${parseInt(blue, 16)}, ${alpha})`
}
