import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router"
import { chartSearch } from "@/areas/data/chart-search"

// The chart page loads with its route, and Lightweight Charts with it, out of the app's first
// bundle (step 5.5, from `BACKLOG.md`).
export const Route = createFileRoute("/_shell/data/chart")({
  validateSearch: chartSearch,
  component: lazyRouteComponent(
    () => import("@/areas/data/ChartPage"),
    "ChartPage"
  ),
})
