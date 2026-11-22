import { createFileRoute } from "@tanstack/react-router"
import { RunsPage } from "@/areas/runs/RunsPage"
import { runsSearch } from "@/areas/runs/run-search"

export const Route = createFileRoute("/_shell/runs/")({
  validateSearch: runsSearch,
  component: RunsPage,
})
