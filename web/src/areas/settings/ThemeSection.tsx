import { useSuspenseQuery } from "@tanstack/react-query"
import { settingsQuery, useThemeChange, type Theme } from "@/api/settings"
import { Label } from "@/ui/label"
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group"
import { showTheme, switchTheme } from "@/ui/theme"
import { SettingsSection } from "./SettingsSection"

const THEMES: readonly Readonly<{ value: Theme; label: string }>[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
]

/** The theme, which the server keeps for every browser; the page switches at once and goes
 * back if the server refuses. */
export function ThemeSection() {
  const { data: settings } = useSuspenseQuery(settingsQuery)
  const change = useThemeChange()
  const shown = change.isPending ? change.variables : settings.theme
  const choose = (value: string) => {
    const chosen = THEMES.find((theme) => theme.value === value)
    if (chosen === undefined) {
      return
    }
    switchTheme(chosen.value)
    change.mutate(chosen.value, { onError: () => showTheme(settings.theme) })
  }

  return (
    <SettingsSection
      title="Appearance"
      description="The colours of every page, kept for each browser you log in from."
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
        <p role="alert" className="text-sm text-negative">
          {change.error.message}
        </p>
      )}
    </SettingsSection>
  )
}
