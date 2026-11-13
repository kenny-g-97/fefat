import { Link } from "@tanstack/react-router"
import { useSyncCover } from "@/api/catalog"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { ImportedDataPanels } from "./ImportedDataPanels"
import { InstrumentsPanel } from "./InstrumentsPanel"
import { SourcesPanel } from "./SourcesPanel"

/** The Data page (step 5.4): Import data in its header; the data the trader imported, a row an
 * instrument's from one provider with its quality, which opens its dataset's page; the
 * catalog's products without data; the instruments; and the source guide. Each section loads,
 * and fails, on its own. */
export function DataPage() {
  const syncs = useSyncCover()
  return (
    <Page
      title="Data"
      description="Your market data and how clean it is, the instruments, and where to get more"
      action={
        <Button asChild>
          <Link to="/data/import">Import data</Link>
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        <ImportedDataPanels syncs={syncs} />
        <InstrumentsPanel />
        <SourcesPanel />
      </div>
    </Page>
  )
}
