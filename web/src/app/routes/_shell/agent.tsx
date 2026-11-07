import { createFileRoute } from "@tanstack/react-router"
import { AgentPage } from "@/areas/agent/AgentPage"

export const Route = createFileRoute("/_shell/agent")({ component: AgentPage })
