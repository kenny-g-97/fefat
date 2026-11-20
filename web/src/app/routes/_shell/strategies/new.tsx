import { createFileRoute } from "@tanstack/react-router"
import { NewStrategyPage } from "@/areas/strategies/NewStrategyPage"

export const Route = createFileRoute("/_shell/strategies/new")({
  component: NewStrategyPage,
})
