import { createFileRoute } from "@tanstack/react-router"
import { AllResultsPage } from "@/areas/runs/AllResultsPage"
import { allResultsSearch } from "@/areas/runs/run-search"

// `run_` keeps the page out from under the run page's route, which renders no outlet.
export const Route = createFileRoute("/_shell/runs/run_/results")({
  validateSearch: allResultsSearch,
  component: AllResultsPage,
})
