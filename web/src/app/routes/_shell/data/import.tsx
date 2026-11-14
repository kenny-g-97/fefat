import { createFileRoute } from "@tanstack/react-router"
import { z } from "zod"
import { ImportPage } from "@/areas/data/ImportPage"

const importSearch = z.object({
  preset: z.string().optional().catch(undefined),
})

export const Route = createFileRoute("/_shell/data/import")({
  validateSearch: importSearch,
  component: ImportPage,
})
