import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router"
import { tradesSearch } from "@/areas/runs/run-search"

// `run_` keeps the page out from under the run page's route, which renders no outlet; the page
// loads with TanStack Table and Virtual, which no other page reads.
export const Route = createFileRoute("/_shell/runs/run_/trades")({
  validateSearch: tradesSearch,
  component: lazyRouteComponent(
    () => import("@/areas/runs/TradesPage"),
    "TradesPage"
  ),
})
