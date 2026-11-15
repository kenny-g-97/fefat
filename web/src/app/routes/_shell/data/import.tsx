import { createFileRoute } from "@tanstack/react-router"
import { ImportPage } from "@/areas/data/ImportPage"
import { importSearch } from "@/areas/data/import/import-search"

export const Route = createFileRoute("/_shell/data/import")({
  validateSearch: importSearch,
  component: ImportPage,
})
