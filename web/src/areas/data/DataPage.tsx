import { Link, useLocation } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { useSyncCover } from "@/api/catalog"
import { Button } from "@/ui/button"
import { Page } from "@/ui/page"
import { ImportedDataPanels } from "./ImportedDataPanels"
import { ImportedSourcesPanel } from "./ImportedSourcesPanel"

/** The Data page (step 5.4): Import data in its header; the data the trader imported, a row an
 * instrument's from one provider with its type and its quality, which opens its dataset's page,
 * under a search and a dropdown each for the instrument, the provider, the type, and the
 * quality; the catalog's products without data; and the sources the data came from, with the
 * way to the guide's page. Each section loads, and fails, on its own. After a delete from a
 * dataset's page, one line over the list says what was deleted (step 5.18). */
export function DataPage() {
  const syncs = useSyncCover()
  const deleted = useLocation({ select: (location) => location.state.deleted })
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
        {deleted !== undefined && <DeletedLine deleted={deleted} />}
        <ImportedDataPanels syncs={syncs} />
        <ImportedSourcesPanel syncs={syncs} />
      </div>
    </Page>
  )
}

/** What a delete from a dataset's page removed, which takes the focus as the page opens, so that a
 * screen reader reads it on arrival (step 5.18). */
function DeletedLine({ deleted }: Readonly<{ deleted: string }>) {
  const line = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (line.current === null) {
      throw new Error("Expected the line that says what was deleted, got none.")
    }
    line.current.focus()
  }, [])
  return (
    <p
      ref={line}
      role="status"
      tabIndex={-1}
      className="text-foreground-secondary"
    >
      Deleted {deleted}.
    </p>
  )
}
