import { createFileRoute } from "@tanstack/react-router"
import { PropPage } from "@/areas/prop/PropPage"

export const Route = createFileRoute("/_shell/prop")({ component: PropPage })
