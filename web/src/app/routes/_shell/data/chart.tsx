import { createFileRoute } from "@tanstack/react-router"
import { ChartPage } from "@/areas/data/ChartPage"
import { chartSearch } from "@/areas/data/chart-search"

export const Route = createFileRoute("/_shell/data/chart")({
  validateSearch: chartSearch,
  component: ChartPage,
})
