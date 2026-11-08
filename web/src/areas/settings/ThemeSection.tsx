import { useSuspenseQuery } from "@tanstack/react-query"
import { settingsQuery, useThemeChange, type Theme } from "@/api/settings"
import { Label } from "@/ui/label"
import { Panel } from "@/ui/panel"
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group"

const THEMES: readonly Readonly<{ value: Theme; label: string }>[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
]

/** The theme, which the server keeps for every browser; the shell paints it once the server
 * has kept it, so that a refusal changes nothing on the page. */
export function ThemeSection() {
  const { data: settings } = useSuspenseQuery(settingsQuery)
  const change = useThemeChange()
  const shown = change.isPending ? change.variables : settings.theme
  const choose = (value: string) => {
    const chosen = THEMES.find((theme) => theme.value === value)
    if (chosen === undefined) {
      throw new Error(
        `Expected the theme dark or light, got ${JSON.stringify(value)}.`
      )
    }
    change.mutate(chosen.value)
  }

  return (
    <Panel
      title="Appearance"
      description="The colours of every page, the same in every browser you log in from"
    >
      <RadioGroup
        aria-label="Theme"
        value={shown}
        onValueChange={choose}
        className="flex gap-6"
      >
        {THEMES.map(({ value, label }) => (
          <div key={value} className="flex items-center gap-2">
            <RadioGroupItem id={`theme-${value}`} value={value} />
            <Label htmlFor={`theme-${value}`}>{label}</Label>
          </div>
        ))}
      </RadioGroup>
      {change.error !== null && (
        <p role="alert" className="text-negative">
          {change.error.message}
        </p>
      )}
    </Panel>
  )
}
