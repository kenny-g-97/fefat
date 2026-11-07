import { useSuspenseQuery } from "@tanstack/react-query"
import { settingsQuery } from "@/api/settings"
import { Page } from "@/ui/page"
import { ApiTokensSection } from "./ApiTokensSection"
import { PasswordSection } from "./PasswordSection"
import { SettingsSection } from "./SettingsSection"
import { ThemeSection } from "./ThemeSection"

/** The settings, one level deep (the design brief): the theme, the password, the API tokens,
 * and the data folder, read-only; the model defaults join with step 8.2. */
export function SettingsPage() {
  return (
    <Page title="Settings">
      <div className="flex max-w-2xl flex-col gap-6">
        <ThemeSection />
        <PasswordSection />
        <ApiTokensSection />
        <DataFolderSection />
      </div>
    </Page>
  )
}

function DataFolderSection() {
  const { data: settings } = useSuspenseQuery(settingsQuery)
  return (
    <SettingsSection
      title="Data folder"
      description={
        <>
          Where your market data lives; set{" "}
          <code className="font-mono">FEFAT_DATA_DIR</code> before{" "}
          <code className="font-mono">fefat up</code> to use another.
        </>
      }
    >
      <code
        data-testid="data-folder"
        aria-label="Data folder"
        className="w-fit max-w-full truncate rounded-md border bg-muted px-3 py-2 font-mono text-sm"
      >
        {settings.data_dir}
      </code>
    </SettingsSection>
  )
}
