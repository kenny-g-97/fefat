import { X } from "lucide-react"
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

/** A setting's options, each a value and the word that names it. */
type Options<Option extends string> = readonly Readonly<{
  value: Option
  label: string
}>[]

const BODIES: Options<ChartStyle["up_body"]> = [
  { value: "hollow", label: "Hollow" },
  { value: "filled", label: "Filled" },
]
const SHOWN_OR_HIDDEN: Options<"shown" | "hidden"> = [
  { value: "shown", label: "Shown" },
  { value: "hidden", label: "Hidden" },
]
const VOLUME_COLOURS: Options<ChartStyle["volume_colouring"]> = [
  { value: "neutral", label: "Grey" },
  { value: "direction", label: "By direction" },
]
const SESSIONS: Options<"shaded" | "plain"> = [
  { value: "shaded", label: "Shaded" },
  { value: "plain", label: "Plain" },
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
          <Setting
            label="Rising bars"
            options={BODIES}
            value={style.up_body}
            onChange={(up_body) => keep((drawn) => ({ ...drawn, up_body }))}
          />
          <Setting
            label="Falling bars"
            options={BODIES}
            value={style.down_body}
            onChange={(down_body) => keep((drawn) => ({ ...drawn, down_body }))}
          />
          <Colours style={style} theme={theme} onKeep={keep} />
          <Setting
            label="Volume"
            options={SHOWN_OR_HIDDEN}
            value={style.volume_shown ? "shown" : "hidden"}
            onChange={(chosen) =>
              keep((drawn) => ({ ...drawn, volume_shown: chosen === "shown" }))
            }
          />
          <Setting
            label="Volume colour"
            options={VOLUME_COLOURS}
            value={style.volume_colouring}
            onChange={(volume_colouring) =>
              keep((drawn) => ({ ...drawn, volume_colouring }))
            }
          />
          <Setting
            label="Grid"
            options={SHOWN_OR_HIDDEN}
            value={style.grid_shown ? "shown" : "hidden"}
            onChange={(chosen) =>
              keep((drawn) => ({ ...drawn, grid_shown: chosen === "shown" }))
            }
          />
          <Setting
            label="Sessions"
            options={SESSIONS}
            value={style.sessions_shaded ? "shaded" : "plain"}
            onChange={(chosen) =>
              keep((drawn) => ({
                ...drawn,
                sessions_shaded: chosen === "shaded",
              }))
            }
          />
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

type SettingProps<Option extends string> = Readonly<{
  label: string
  options: Options<Option>
  value: Option
  onChange: (chosen: Option) => void
}>

/** A setting of a few short options, in a row with its label. */
function Setting<Option extends string>({
  label,
  options,
  value,
  onChange,
}: SettingProps<Option>) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="font-medium text-foreground">{label}</span>
      <Segmented
        label={label}
        options={options}
        value={value}
        onChange={onChange}
      />
    </div>
  )
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
