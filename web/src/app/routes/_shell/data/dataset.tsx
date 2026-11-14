import { createFileRoute } from "@tanstack/react-router"
import { DatasetPage } from "@/areas/data/DatasetPage"
import { datasetSearch } from "@/areas/data/chart-search"

export const Route = createFileRoute("/_shell/data/dataset")({
  validateSearch: datasetSearch,
  component: DatasetPage,
})
