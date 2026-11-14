import { createFileRoute } from "@tanstack/react-router"
import { DataPage } from "@/areas/data/DataPage"

export const Route = createFileRoute("/_shell/data/")({ component: DataPage })
