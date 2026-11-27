import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router"
import { compareSearch } from "@/areas/runs/run-search"

export const Route = createFileRoute("/_shell/runs/compare")({
  validateSearch: compareSearch,
  component: lazyRouteComponent(
    () => import("@/areas/runs/ComparePage"),
    "ComparePage"
  ),
})
