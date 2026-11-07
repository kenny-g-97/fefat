import { createFileRoute } from "@tanstack/react-router"
import { HomePage } from "@/areas/home/HomePage"

export const Route = createFileRoute("/_shell/")({ component: HomePage })
