import { Link } from "@tanstack/react-router"
import { useSyncCover } from "@/api/catalog"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { ImportedDataPanels } from "./ImportedDataPanels"
import { ImportedSourcesPanel } from "./ImportedSourcesPanel"

/** The Data page (step 5.4): Import data in its header; the data the trader imported, a row an
 * instrument's from one provider with its type and its quality, which opens its dataset's page,
 * under a search and a dropdown each for the instrument, the provider, the type, and the
 * quality; the catalog's products without data; and the sources the data came from, with the
 * way to the guide's page. Each section loads, and fails, on its own. */
export function DataPage() {
  const syncs = useSyncCover()
  return (
    <Page
      title="Data"
      description="Your market data, how clean it is, and the sources it came from"
      action={
        <Button asChild>
          <Link to="/data/import">Import data</Link>
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        <ImportedDataPanels syncs={syncs} />
        <ImportedSourcesPanel syncs={syncs} />
      </div>
    </Page>
  )
}
