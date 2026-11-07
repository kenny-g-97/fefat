import { createFileRoute } from "@tanstack/react-router"
import { apiTokensQuery } from "@/api/api-tokens"
import { SettingsPage } from "@/areas/settings/SettingsPage"

export const Route = createFileRoute("/_shell/settings")({
  loader: ({ context }) => context.queryClient.ensureQueryData(apiTokensQuery),
  component: SettingsPage,
})
