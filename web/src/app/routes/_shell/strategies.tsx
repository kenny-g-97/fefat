import { createFileRoute } from "@tanstack/react-router"
import { StrategiesPage } from "@/areas/strategies/StrategiesPage"

export const Route = createFileRoute("/_shell/strategies")({
  component: StrategiesPage,
})
