import { createFileRoute } from "@tanstack/react-router"
import { RunsPage } from "@/areas/runs/RunsPage"

export const Route = createFileRoute("/_shell/runs")({ component: RunsPage })
