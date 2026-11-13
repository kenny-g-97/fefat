import { Link } from "@tanstack/react-router"
import { useSyncCover } from "@/api/catalog"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { CatalogPanels } from "./CatalogPanels"
import { InstrumentsPanel } from "./InstrumentsPanel"
import { SourcesPanel } from "./SourcesPanel"

/** The Data page (step 5.4): the catalog's products and your own data, each root with its
 * quality and its coverage by month, which Update checks again as a job; the instruments; and
 * the source guide. Each section loads, and fails, on its own. */
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
        <CatalogPanels syncs={syncs} />
        <InstrumentsPanel />
        <SourcesPanel />
      </div>
    </Page>
  )
}
