import { createFileRoute } from "@tanstack/react-router"
import { StrategyPage } from "@/areas/strategies/StrategyPage"
import { strategySearch } from "@/areas/strategies/strategy-names"

export const Route = createFileRoute("/_shell/strategies/strategy")({
  validateSearch: strategySearch,
  component: StrategyPage,
})
