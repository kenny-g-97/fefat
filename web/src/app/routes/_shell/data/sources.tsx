import { createFileRoute } from "@tanstack/react-router"
import { SourcesPage } from "@/areas/data/SourcesPage"

export const Route = createFileRoute("/_shell/data/sources")({
  component: SourcesPage,
})
