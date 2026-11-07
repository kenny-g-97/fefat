import { createFileRoute } from "@tanstack/react-router"
import { LabPage } from "@/areas/lab/LabPage"

export const Route = createFileRoute("/_shell/lab")({ component: LabPage })
