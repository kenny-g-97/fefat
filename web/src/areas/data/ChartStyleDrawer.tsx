import { X } from "lucide-react"
import type { ReactNode } from "react"
import type { components } from "@/api/schema"
import {
  type ChartStyle,
  type ChartStyleChange,
  FEATS_CHART_STYLE,
  previewChartStyle,
  type Theme,
  useChartStyleChange,
} from "@/api/settings"
import { readThemeTokens, type ThemeTokens } from "@/charts/chart-look"
import { Button } from "@/ui/button"
import { ColourField } from "@/ui/colour-field"
import { Segmented } from "@/ui/segmented"
import { Sheet, SheetClose, SheetContent, SheetTitle } from "@/ui/sheet"
import { useShownTheme } from "@/ui/theme"

type ThemeColours = components["schemas"]["ThemeColours"]
type Colour = keyof ThemeColours

const BODIES: readonly Readonly<{
  value: ChartStyle["up_body"]
  label: string
}>[] = [
  { value: "hollow", label: "Hollow" },
  { value: "filled", label: "Filled" },
]

/** Each colour the trader may pick, and the token a theme gives it. */
const COLOURS: readonly Readonly<{
  key: Colour
  label: string
  token: keyof ThemeTokens
}>[] = [
  { key: "up", label: "Rising", token: "positive" },
  { key: "down", label: "Falling", token: "negative" },
  { key: "background", label: "Background", token: "card" },
  { key: "grid", label: "Grid", token: "border" },
  { key: "text", label: "Text", token: "mutedForeground" },
]

type ChartStyleDrawerProps = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  style: ChartStyle
}>

/** The chart style drawer (web/DESIGN.md, Patterns, Chart style drawer): the jobs drawer's
 * sheet, open while the trader works on the chart beside it, each choice drawn at once and kept
 * by the server for every chart and browser; a colour belongs to the theme it is picked in. */
export function ChartStyleDrawer({
  open,
  onOpenChange,
  style,
}: ChartStyleDrawerProps) {
  const theme = useShownTheme()
  const { keep, error } = useChartStyleChange()
  const shown = shownSwitch(style)
  return (
    <Sheet modal={false} open={open} onOpenChange={onOpenChange}>
      <SheetContent
        showCloseButton={false}
        aria-describedby={undefined}
        data-testid="chart-style-drawer"
        className="gap-0"
        onInteractOutside={(event) => event.preventDefault()}
      >
        <header className="flex h-18 shrink-0 items-center justify-between border-b px-6">
          <SheetTitle className="text-base">Chart style</SheetTitle>
          <SheetClose asChild>
            <Button
              data-slot="button"
              variant="ghost"
              size="icon-lg"
              aria-label="Close"
            >
              <X className="size-5" />
            </Button>
          </SheetClose>
        </header>
        <div
          data-testid="chart-style-settings"
          className="flex flex-1 flex-col gap-4 overflow-y-auto px-6 py-5"
        >
          <Setting label="Rising bars">
            <Segmented
              label="Rising bars"
              options={BODIES}
              value={style.up_body}
              onChange={(up_body) => keep((drawn) => ({ ...drawn, up_body }))}
            />
          </Setting>
          <Setting label="Falling bars">
            <Segmented
              label="Falling bars"
              options={BODIES}
              value={style.down_body}
              onChange={(down_body) =>
                keep((drawn) => ({ ...drawn, down_body }))
              }
            />
          </Setting>
          <Colours style={style} theme={theme} onKeep={keep} />
          {shown.map(({ label, options, value, change }) => (
            <Setting key={label} label={label}>
              <Segmented
                label={label}
                options={options}
                value={value}
                onChange={(chosen) => keep((drawn) => change(drawn, chosen))}
              />
            </Setting>
          ))}
          <Button
            variant="ghost"
            className="self-start"
            onClick={() => keep(() => FEATS_CHART_STYLE)}
          >
            Reset to FEAT's style
          </Button>
          {error !== null && (
            <p role="alert" className="text-negative">
              {error.message}
            </p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function Colours({
  style,
  theme,
  onKeep,
}: Readonly<{
  style: ChartStyle
  theme: Theme
  onKeep: (change: ChartStyleChange) => void
}>) {
  const tokens = readThemeTokens()
  const own = style[theme]
  return (
    <section
      aria-label={`Colours in the ${theme} theme`}
      className="flex flex-col gap-2"
    >
      <h3 className="font-medium text-foreground">
        Colours in the {theme} theme
      </h3>
      {COLOURS.map(({ key, label, token }) => {
        const colour = own[key]
        return (
          <ColourField
            key={key}
            id={`chart-colour-${key}`}
            label={label}
            colour={colour ?? tokens[token]}
            own={colour !== null && colour !== undefined}
            onPreview={(picked) =>
              previewChartStyle((drawn) =>
                withColour(drawn, theme, key, picked)
              )
            }
            onKeep={(picked) =>
              onKeep((drawn) => withColour(drawn, theme, key, picked))
            }
            onReset={() =>
              onKeep((drawn) => withColour(drawn, theme, key, null))
            }
          />
        )
      })}
    </section>
  )
}

function Setting({
  label,
  children,
}: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="font-medium text-foreground">{label}</span>
      {children}
    </div>
  )
}

type Switch = Readonly<{
  label: string
  options: readonly Readonly<{ value: string; label: string }>[]
  value: string
  change: (drawn: ChartStyle, chosen: string) => ChartStyle
}>

/** The style's choices of two words each, as `style` has them: the volume pane shown and how it
 * is coloured, the grid, and the sessions' shading. */
function shownSwitch(style: ChartStyle): readonly Switch[] {
  const shownOrHidden = [
    { value: "shown", label: "Shown" },
    { value: "hidden", label: "Hidden" },
  ]
  return [
    {
      label: "Volume",
      options: shownOrHidden,
      value: style.volume_shown ? "shown" : "hidden",
      change: (drawn, chosen) => ({
        ...drawn,
        volume_shown: chosen === "shown",
      }),
    },
    {
      label: "Volume colour",
      options: [
        { value: "neutral", label: "Grey" },
        { value: "direction", label: "By direction" },
      ],
      value: style.volume_colouring,
      change: (drawn, chosen) => ({
        ...drawn,
        volume_colouring: chosen === "direction" ? "direction" : "neutral",
      }),
    },
    {
      label: "Grid",
      options: shownOrHidden,
      value: style.grid_shown ? "shown" : "hidden",
      change: (drawn, chosen) => ({ ...drawn, grid_shown: chosen === "shown" }),
    },
    {
      label: "Sessions",
      options: [
        { value: "shaded", label: "Shaded" },
        { value: "plain", label: "Plain" },
      ],
      value: style.sessions_shaded ? "shaded" : "plain",
      change: (drawn, chosen) => ({
        ...drawn,
        sessions_shaded: chosen === "shaded",
      }),
    },
  ]
}

/** `style` with the colour `key` of `theme` set to `colour`, or to the theme's own where null. */
function withColour(
  style: ChartStyle,
  theme: Theme,
  key: Colour,
  colour: string | null
): ChartStyle {
  const colours = { ...style[theme], [key]: colour }
  return theme === "dark"
    ? { ...style, dark: colours }
    : { ...style, light: colours }
}
