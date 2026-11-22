import { createFileRoute } from "@tanstack/react-router"
import { RunPage } from "@/areas/runs/RunPage"
import { runSearch } from "@/areas/runs/run-search"

export const Route = createFileRoute("/_shell/runs/run")({
  validateSearch: runSearch,
  component: RunPage,
})
