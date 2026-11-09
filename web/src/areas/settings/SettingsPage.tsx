import { useSuspenseQuery } from "@tanstack/react-query"
import { settingsQuery } from "@/api/settings"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { ApiTokensSection } from "./ApiTokensSection"
import { DemoJobSection } from "./DemoJobSection"
import { PasswordSection } from "./PasswordSection"
import { ThemeSection } from "./ThemeSection"

/** The settings, one level deep (the design brief), a card each: the theme, the demo job, the
 * password, the API tokens, and the data folder, read-only; the model defaults join with step
 * 8.2. */
export function SettingsPage() {
  return (
    <Page title="Settings">
      <div className="flex max-w-3xl flex-col gap-6">
        <ThemeSection />
        <DemoJobSection />
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
    <Panel
      title="Data folder"
      description={
        <>
          Where your market data lives; set <code>FEFAT_DATA_DIR</code> before{" "}
          <code>fefat up</code> to use another
        </>
      }
    >
      <code
        data-testid="data-folder"
        aria-label="Data folder"
        className="w-fit max-w-full truncate rounded-xl border bg-muted px-3 py-2"
      >
        {settings.data_dir}
      </code>
    </Panel>
  )
}
